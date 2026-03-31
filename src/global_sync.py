from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any

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
    def __init__(self, buffer_path: str | Path = DEFAULT_SYNC_BUFFER_PATH) -> None:
        self.buffer_path = Path(buffer_path)
        self.buffer_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, envelope: SyncEnvelope) -> None:
        with self.buffer_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(envelope.to_record(), ensure_ascii=True, sort_keys=True))
            handle.write("\n")

    def read_all(self) -> list[dict[str, Any]]:
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

    def clear(self) -> None:
        if self.buffer_path.exists():
            self.buffer_path.unlink()
