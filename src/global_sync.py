from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.config_shield import ConfigShield

DEFAULT_SYNC_BUFFER_PATH = Path("data/ops-queue/sync-buffer.jsonl")
DEFAULT_SCHEMA_VERSION = "1.0"

@dataclass(slots=True)
class SyncEnvelope:
    node_id: str
    msg_type: str
    payload: dict[str, Any]
    schema_version: str = DEFAULT_SCHEMA_VERSION
    ts: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ts": self.ts,
            "nodeId": self.node_id,
            "msgType": self.msg_type,
            "payload": self.payload,
        }

class SyncBuffer:
    """
    LockedSyncBuffer (Phase 5 #41).
    使用 ConfigShield 分布式锁确保多节点写入原子性与一致性。
    """
    def __init__(self, shield: ConfigShield, buffer_path: str | Path = DEFAULT_SYNC_BUFFER_PATH) -> None:
        self.shield = shield
        self.buffer_path = Path(buffer_path)
        self.buffer_path.parent.mkdir(parents=True, exist_ok=True)
        # 资源 ID: sync_buffer:<abs_path> (Architect Spec §1)
        self.resource_id = f"sync_buffer:{self.buffer_path.absolute()}"

    def append(self, envelope: SyncEnvelope) -> None:
        # Phase 5 #41: 使用分布式锁，增加 15s 等待时间以应对极高并发竞争场景
        self.shield.acquire(self.resource_id, wait_ms=15000)
        try:
            with self.buffer_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(envelope.to_record(), ensure_ascii=True, sort_keys=True))
                handle.write("\n")
                handle.flush()
                # Admission Spec §1.1: 强制 fsync
                os.fsync(handle.fileno())
        finally:
            self.shield.release(self.resource_id)

    def read_all(self) -> list[dict[str, Any]]:
        self.shield.acquire(self.resource_id, wait_ms=15000)
        try:
            if not self.buffer_path.exists():
                return []
            records: list[dict[str, Any]] = []
            with self.buffer_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    records.append(json.loads(line))
            return records
        finally:
            self.shield.release(self.resource_id)

    def clear(self) -> None:
        self.shield.acquire(self.resource_id, wait_ms=15000)
        try:
            if self.buffer_path.exists():
                self.buffer_path.unlink()
        finally:
            self.shield.release(self.resource_id)
