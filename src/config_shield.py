from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import threading
import time
from src.agent_key_vault import AgentKeyVault
from typing import Callable, Any

try:
    import redis
except ImportError:
    redis = None

DEFAULT_LOCK_DIR = Path("data/locks")
DEFAULT_TTL_MS = 30_000
DEFAULT_HEARTBEAT_INTERVAL_MS = 10_000


class LockAcquisitionError(RuntimeError):
    pass


@dataclass(slots=True)
class LockRecord:
    node_id: str
    resource_path: str
    acquired_at: int
    ttl_ms: int
    heartbeat_at: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "node_id": self.node_id,
            "resource_path": self.resource_path,
            "acquired_at": self.acquired_at,
            "ttl_ms": self.ttl_ms,
            "heartbeat_at": self.heartbeat_at,
        }

    @classmethod
    def from_json(cls, payload: str) -> "LockRecord":
        record = json.loads(payload)
        return cls(
            node_id=str(record["node_id"]),
            resource_path=str(record["resource_path"]),
            acquired_at=int(record["acquired_at"]),
            ttl_ms=int(record["ttl_ms"]),
            heartbeat_at=int(record["heartbeat_at"]),
        )


class ConfigShield:
    def __init__(
        self,
        node_id: str,
        lock_dir: str | Path = DEFAULT_LOCK_DIR,
        *,
        ttl_ms: int = DEFAULT_TTL_MS,
        heartbeat_interval_ms: int = DEFAULT_HEARTBEAT_INTERVAL_MS,
        on_lock_acquired: Callable[[str, str], None] | None = None,
        key_vault: AgentKeyVault | None = None,
        redis_url: str | None = None,
    ) -> None:
        self.node_id = node_id
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_ms = ttl_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.on_lock_acquired = on_lock_acquired
        self.key_vault = key_vault
        self.redis_url = redis_url
        self.redis_client = None
        if redis_url:
            if redis is None:
                raise ImportError("redis-py is required for RedisConfigShield")
            self.redis_client = redis.from_url(redis_url, decode_responses=True)

        self._heartbeat_threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._state_lock = threading.RLock()

    def _redis_key(self, resource_path: str) -> str:
        if resource_path.startswith("sentry:"):
            return resource_path
        return f"sentry:{resource_path}"

    def _acquire_once_redis(self, resource_path: str, ttl_ms: int) -> LockRecord:
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")
        key = self._redis_key(resource_path)
        now = self._utc_ms()
        record = LockRecord(
            node_id=self.node_id,
            resource_path=resource_path,
            acquired_at=now,
            ttl_ms=ttl_ms,
            heartbeat_at=now,
        )
        payload = json.dumps(record.to_dict())
        # Use PX for millisecond TTL
        success = self.redis_client.set(key, payload, nx=True, px=ttl_ms)
        if not success:
            raw = self.redis_client.get(key)
            if raw:
                existing = LockRecord.from_json(raw)
                raise LockAcquisitionError(f"resource is locked by {existing.node_id}: {resource_path}")
            else:
                return self._acquire_once_redis(resource_path, ttl_ms)
        return record

    def get_secret(self, uid: str, did: str, provider: str) -> Any:
        """
        Phase 5 #40: 代理调用 KeyVault 获取敏感凭证，并进行必要的防护检查。
        """
        if self.key_vault is None:
            raise RuntimeError("ConfigShield: KeyVault not initialized")
        return self.key_vault.resolve_keys(uid, did, provider)

    @staticmethod
    def _utc_ms() -> int:
        return int(time.time() * 1000)

    def _lock_path(self, resource_path: str) -> Path:
        digest = hashlib.sha256(resource_path.encode("utf-8")).hexdigest()
        return self.lock_dir / f"{digest}.lock"

    def _write_record(self, lock_path: Path, record: LockRecord) -> None:
        payload = json.dumps(record.to_dict(), ensure_ascii=True, sort_keys=True)
        fd, temp_name = tempfile.mkstemp(dir=self.lock_dir, prefix="lock-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, lock_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _read_record(self, lock_path: Path) -> LockRecord | None:
        if not lock_path.exists():
            return None
        return LockRecord.from_json(lock_path.read_text(encoding="utf-8"))

    def _is_stale(self, record: LockRecord, now_ms: int | None = None) -> bool:
        now = now_ms if now_ms is not None else self._utc_ms()
        return now - record.heartbeat_at > record.ttl_ms

    def _acquire_once(self, resource_path: str, ttl_ms: int) -> LockRecord:
        lock_path = self._lock_path(resource_path)
        now = self._utc_ms()
        record = LockRecord(
            node_id=self.node_id,
            resource_path=resource_path,
            acquired_at=now,
            ttl_ms=ttl_ms,
            heartbeat_at=now,
        )
        payload = json.dumps(record.to_dict(), ensure_ascii=True, sort_keys=True)

        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = self._read_record(lock_path)
            if existing is None:
                return self._acquire_once(resource_path, ttl_ms)
            if not self._is_stale(existing, now):
                raise LockAcquisitionError(f"resource is locked by {existing.node_id}: {resource_path}")

            stale_path = lock_path.with_name(f"{lock_path.name}.{self.node_id}.{now}.stale")
            try:
                os.rename(lock_path, stale_path)
            except FileNotFoundError:
                return self._acquire_once(resource_path, ttl_ms)

            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                if stale_path.exists():
                    stale_path.unlink()
                winner = self._read_record(lock_path)
                owner = winner.node_id if winner is not None else "another node"
                raise LockAcquisitionError(f"lost lock race on stale reclaim to {owner}: {resource_path}") from exc

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if lock_path.exists():
                    lock_path.unlink()
                raise
            finally:
                if stale_path.exists():
                    stale_path.unlink()

            verified = self._read_record(lock_path)
            if verified is None or verified.node_id != self.node_id:
                raise LockAcquisitionError(f"lost lock race on stale reclaim: {resource_path}")
            return verified

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def acquire(self, resource_path: str, *, ttl_ms: int | None = None, wait_ms: int = 0, start_heartbeat: bool = True) -> LockRecord:
        effective_ttl = ttl_ms or self.ttl_ms
        deadline = time.time() + (wait_ms / 1000.0) if wait_ms > 0 else 0
        attempts = 0

        # Exponential Backoff with Jitter configuration (Phase 5 #41 Optimization)
        base_delay = 0.02  # 20ms
        max_delay = 0.2    # 200ms

        while True:
            try:
                with self._state_lock:
                    if self.redis_client:
                        record = self._acquire_once_redis(resource_path, effective_ttl)
                    else:
                        record = self._acquire_once(resource_path, effective_ttl)

                    if start_heartbeat:
                        self._start_heartbeat(resource_path, effective_ttl)
                    if self.on_lock_acquired is not None:
                        self.on_lock_acquired(resource_path, self.node_id)
                    return record
            except (LockAcquisitionError, OSError, PermissionError, redis.RedisError if redis else Exception) as e:
                # Check if it's a transient error or a lock contention
                is_transient = False
                if isinstance(e, (OSError, PermissionError)):
                    win_err = getattr(e, "winerror", 0)
                    if win_err in (5, 32) or (isinstance(e, PermissionError) and sys.platform == "win32"):
                        is_transient = True
                elif redis and isinstance(e, redis.RedisError):
                    is_transient = True
                else:
                    is_transient = True # LockAcquisitionError is contention

                if not is_transient:
                    raise

                if deadline == 0 or time.time() >= deadline:
                    if isinstance(e, (OSError, PermissionError)):
                        raise LockAcquisitionError(f"transient file busy/denied on {resource_path}") from e
                    raise

                attempts += 1
                current_cap = min(max_delay, base_delay * (2 ** attempts))
                delay = random.uniform(0, current_cap)

                time_left = deadline - time.time()
                if delay > time_left:
                    delay = time_left

                if delay > 0:
                    time.sleep(delay)
                else:
                    pass

    def _start_heartbeat(self, resource_path: str, ttl_ms: int) -> None:
        if resource_path in self._heartbeat_threads:
            return
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(resource_path, ttl_ms, stop_event),
            daemon=True,
            name=f"config-shield:{resource_path}",
        )
        self._heartbeat_threads[resource_path] = (thread, stop_event)
        thread.start()

    def _heartbeat_loop(self, resource_path: str, ttl_ms: int, stop_event: threading.Event) -> None:
        interval = max(self.heartbeat_interval_ms / 1000, 0.1)
        while not stop_event.wait(interval):
            try:
                self.heartbeat(resource_path, ttl_ms=ttl_ms)
            except LockAcquisitionError:
                return

    def heartbeat(self, resource_path: str, *, ttl_ms: int | None = None) -> LockRecord:
        effective_ttl = ttl_ms or self.ttl_ms
        with self._state_lock:
            if self.redis_client:
                key = self._redis_key(resource_path)
                raw = self.redis_client.get(key)
                if not raw:
                    raise LockAcquisitionError(f"lock not found in Redis: {resource_path}")
                record = LockRecord.from_json(raw)
                if record.node_id != self.node_id:
                    raise LockAcquisitionError(f"lock owned by another node: {resource_path}")
                now = self._utc_ms()
                refreshed = LockRecord(
                    node_id=self.node_id,
                    resource_path=resource_path,
                    acquired_at=record.acquired_at,
                    ttl_ms=effective_ttl,
                    heartbeat_at=now,
                )
                self.redis_client.set(key, json.dumps(refreshed.to_dict()), xx=True, px=effective_ttl)
                return refreshed
            else:
                lock_path = self._lock_path(resource_path)
                record = self._read_record(lock_path)
                if record is None:
                    raise LockAcquisitionError(f"lock not found: {resource_path}")
                if record.node_id != self.node_id and not self._is_stale(record):
                    raise LockAcquisitionError(f"lock owned by another node: {resource_path}")
                now = self._utc_ms()
                refreshed = LockRecord(
                    node_id=self.node_id,
                    resource_path=resource_path,
                    acquired_at=record.acquired_at,
                    ttl_ms=effective_ttl,
                    heartbeat_at=now,
                )
                self._write_record(lock_path, refreshed)
                return refreshed

    def release(self, resource_path: str, *, force: bool = False) -> None:
        with self._state_lock:
            heartbeat_state = self._heartbeat_threads.pop(resource_path, None)
            if heartbeat_state is not None:
                thread, stop_event = heartbeat_state
                stop_event.set()
                thread.join(timeout=1)

            if self.redis_client:
                key = self._redis_key(resource_path)
                if force:
                    self.redis_client.delete(key)
                    return
                raw = self.redis_client.get(key)
                if not raw:
                    return
                record = LockRecord.from_json(raw)
                if record.node_id == self.node_id:
                    self.redis_client.delete(key)
                else:
                    raise LockAcquisitionError(f"cannot release lock owned by {record.node_id}: {resource_path}")
            else:
                lock_path = self._lock_path(resource_path)
                record = self._read_record(lock_path)
                if record is None:
                    return
                if not force and record.node_id != self.node_id and not self._is_stale(record):
                    raise LockAcquisitionError(f"lock owned by another node: {resource_path}")
                if lock_path.exists():
                    lock_path.unlink()

    def inspect(self, resource_path: str) -> LockRecord | None:
        with self._state_lock:
            if self.redis_client:
                key = self._redis_key(resource_path)
                raw = self.redis_client.get(key)
                return LockRecord.from_json(raw) if raw else None
            else:
                return self._read_record(self._lock_path(resource_path))
