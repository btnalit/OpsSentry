import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

try:
    import redis
except ImportError:
    redis = None

from src.ops_ledger import OpsLedger
from src.ledger_entry import LedgerEntry

# Log setup for visibility
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("OpsShipper")

DEFAULT_SHIP_INTERVAL = 1.0  # 1 second
DEFAULT_BATCH_SIZE = 100
DEFAULT_CHECKPOINT_PATH = Path("data/ops-queue/shipper.checkpoint")

class AuditShipper:
    """
    Phase 7 #62: 分布式审计流聚合 Shipper 原型。
    采用 Background Shipper (Tail) 模式，从本地 SQLite 异步同步增量审计流至 Redis Streams。
    支持断线重连、断点续传及指数退避重试。
    """
    
    def __init__(
        self,
        node_id: str,
        redis_url: str,
        ledger: OpsLedger,
        checkpoint_path: str | Path = DEFAULT_CHECKPOINT_PATH,
        ship_interval: float = DEFAULT_SHIP_INTERVAL,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.node_id = node_id
        self.redis_url = redis_url
        self.ledger = ledger
        self.checkpoint_path = Path(checkpoint_path)
        self.ship_interval = ship_interval
        self.batch_size = batch_size
        
        if redis is None:
            raise ImportError("redis-py is required for AuditShipper")
            
        self._redis_client = redis.from_url(redis_url, decode_responses=True)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream_key = f"sentry:audit:stream:{self.node_id}"
        
        # Ensure checkpoint directory exists
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Internal state for tracking progress
        self._last_ts, self._last_id = self._load_checkpoint()
        logger.info(f"Initialized Shipper for {node_id}, starting from TS={self._last_ts}, ID={self._last_id}")

    def _load_checkpoint(self) -> tuple[int, str]:
        """从物理文件恢复上一次上报的断点"""
        if not self.checkpoint_path.exists():
            return 0, ""
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            return int(data.get("last_ts", 0)), str(data.get("last_id", ""))
        except (json.JSONDecodeError, ValueError, KeyError):
            logger.warning(f"Corrupted checkpoint file: {self.checkpoint_path}, starting from 0")
            return 0, ""

    def _save_checkpoint(self, ts: int, entry_id: str) -> None:
        """持久化断点信息"""
        data = {"last_ts": ts, "last_id": entry_id, "updated_at": int(time.time() * 1000)}
        # Atomic write
        temp_path = self.checkpoint_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data), encoding="utf-8")
        temp_path.replace(self.checkpoint_path)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name=f"shipper-{self.node_id}")
        self._thread.start()
        logger.info(f"AuditShipper started for node: {self.node_id}")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            logger.info("AuditShipper stopped.")

    def _run_loop(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                shipped_count = self._ship_batch()
                consecutive_failures = 0 # Reset on success
                
                # If we shipped a full batch, don't wait as long to catch up
                interval = 0.1 if shipped_count >= self.batch_size else self.ship_interval
                if self._stop_event.wait(interval):
                    break
            except Exception as e:
                consecutive_failures += 1
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s... cap at 60s
                wait_time = min(60, 2 ** (consecutive_failures - 1))
                logger.error(f"Shipper failure (attempt {consecutive_failures}): {e}. Retrying in {wait_time}s...")
                if self._stop_event.wait(wait_time):
                    break

    def _ship_batch(self) -> int:
        """
        核心上报逻辑：
        1. 从本地获取增量数据。
        2. 批量推送到 Redis Stream。
        3. 成功后更新 checkpoint。
        """
        # Fetch incremental entries from SQLite via OpsLedger's storage
        entries = self.ledger.storage.get_incremental(self._last_ts, self._last_id, limit=self.batch_size)
        if not entries:
            return 0

        # Push to Redis Stream in a pipeline for performance
        pipe = self._redis_client.pipeline()
        for entry in entries:
            # Prepare payload
            payload = {
                "id": entry.id,
                "ts": entry.created_at,
                "data": json.dumps(entry.to_record())
            }
            # XADD key ID field value [field value ...]
            # We use '*' for auto-id, but the payload contains the source ID for idempotency
            pipe.xadd(self._stream_key, payload)
        
        # Execute batch
        pipe.execute()
        
        # Update progress tracking
        last_entry = entries[-1]
        self._last_ts = last_entry.created_at
        self._last_id = last_entry.id
        self._save_checkpoint(self._last_ts, self._last_id)
        
        if len(entries) > 0:
            logger.debug(f"Shipped {len(entries)} audit entries to Redis Stream.")
            
        return len(entries)
