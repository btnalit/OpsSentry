from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


VALID_STATUSES = {"pending", "running", "completed", "failed"}
VALID_TRANSITIONS = {
    "pending": {"running", "failed"},
    "running": {"completed", "failed", "pending"},
    "completed": set(),
    "failed": {"pending"},
}


class LedgerError(RuntimeError):
    pass


class LedgerEntryNotFound(LedgerError):
    pass


class LedgerStateError(LedgerError):
    pass


def utc_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class LedgerEntry:
    id: str
    action: str
    status: str = "pending"
    checkpoint: dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=utc_ms)
    updated_at: int = field(default_factory=utc_ms)
    accio_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise LedgerStateError(f"unsupported status: {self.status}")

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "LedgerEntry":
        return cls(
            id=str(record["id"]),
            action=str(record["action"]),
            status=str(record.get("status", "pending")),
            checkpoint=dict(record.get("checkpoint") or {}),
            created_at=int(record.get("created_at", utc_ms())),
            updated_at=int(record.get("updated_at", utc_ms())),
            accio_ref=record.get("accio_ref") or record.get("accio_task_ref"),
            metadata=dict(record.get("metadata") or {}),
            last_error=record.get("last_error"),
        )

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "checkpoint": self.checkpoint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
        if self.accio_ref is not None:
            record["accio_ref"] = self.accio_ref
        if self.last_error is not None:
            record["last_error"] = self.last_error
        return record
