from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
import uuid

DEFAULT_LEDGER_PATH = Path("data/ops-queue/ledger.jsonl")
VALID_STATUSES = {"pending", "running", "completed", "failed"}


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
    accio_task_ref: str | None = None
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
            accio_task_ref=record.get("accio_task_ref"),
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
        if self.accio_task_ref is not None:
            record["accio_task_ref"] = self.accio_task_ref
        if self.last_error is not None:
            record["last_error"] = self.last_error
        return record


class OpsLedger:
    def __init__(self, ledger_path: str | Path = DEFAULT_LEDGER_PATH) -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._entries: dict[str, LedgerEntry] = self._load_entries()

    def _load_entries(self) -> dict[str, LedgerEntry]:
        entries: dict[str, LedgerEntry] = {}
        if not self.ledger_path.exists():
            return entries

        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                entry = LedgerEntry.from_record(record)
                entries[entry.id] = entry
        return entries

    def _persist(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=self.ledger_path.parent,
            prefix="ledger-",
            suffix=".tmp",
        ) as handle:
            temp_path = Path(handle.name)
            for entry in sorted(self._entries.values(), key=lambda item: (item.created_at, item.id)):
                handle.write(json.dumps(entry.to_record(), ensure_ascii=True, sort_keys=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, self.ledger_path)

    def _get_entry(self, entry_id: str) -> LedgerEntry:
        try:
            return self._entries[entry_id]
        except KeyError as exc:
            raise LedgerEntryNotFound(entry_id) from exc

    def create_entry(
        self,
        action: str,
        *,
        entry_id: str | None = None,
        accio_task_ref: str | None = None,
        checkpoint: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        with self._lock:
            identifier = entry_id or str(uuid.uuid4())
            if identifier in self._entries:
                raise LedgerStateError(f"duplicate ledger id: {identifier}")

            entry = LedgerEntry(
                id=identifier,
                action=action,
                status="pending",
                checkpoint=dict(checkpoint or {}),
                accio_task_ref=accio_task_ref,
                metadata=dict(metadata or {}),
            )
            self._entries[entry.id] = entry
            self._persist()
            return LedgerEntry.from_record(entry.to_record())

    def list_entries(self, *, status: str | None = None) -> list[LedgerEntry]:
        with self._lock:
            entries = list(self._entries.values())
            if status is not None:
                if status not in VALID_STATUSES:
                    raise LedgerStateError(f"unsupported status: {status}")
                entries = [entry for entry in entries if entry.status == status]
            return [LedgerEntry.from_record(entry.to_record()) for entry in sorted(entries, key=lambda item: (item.created_at, item.id))]

    def get_entry(self, entry_id: str) -> LedgerEntry:
        with self._lock:
            entry = self._get_entry(entry_id)
            return LedgerEntry.from_record(entry.to_record())

    def transition(
        self,
        entry_id: str,
        status: str,
        *,
        checkpoint: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> LedgerEntry:
        if status not in VALID_STATUSES:
            raise LedgerStateError(f"unsupported status: {status}")

        with self._lock:
            entry = self._get_entry(entry_id)
            entry.status = status
            if checkpoint is not None:
                entry.checkpoint = dict(checkpoint)
            if error is not None:
                entry.last_error = error
            elif status != "failed":
                entry.last_error = None
            entry.updated_at = utc_ms()
            self._persist()
            return LedgerEntry.from_record(entry.to_record())

    def mark_running(self, entry_id: str, *, checkpoint: dict[str, Any] | None = None) -> LedgerEntry:
        return self.transition(entry_id, "running", checkpoint=checkpoint)

    def update_checkpoint(self, entry_id: str, checkpoint: dict[str, Any]) -> LedgerEntry:
        with self._lock:
            entry = self._get_entry(entry_id)
            if entry.status not in {"pending", "running"}:
                raise LedgerStateError(f"cannot checkpoint entry in status {entry.status}")
            entry.checkpoint = dict(checkpoint)
            entry.updated_at = utc_ms()
            self._persist()
            return LedgerEntry.from_record(entry.to_record())

    def mark_completed(self, entry_id: str, *, checkpoint: dict[str, Any] | None = None) -> LedgerEntry:
        return self.transition(entry_id, "completed", checkpoint=checkpoint)

    def mark_failed(self, entry_id: str, error: str, *, checkpoint: dict[str, Any] | None = None) -> LedgerEntry:
        return self.transition(entry_id, "failed", checkpoint=checkpoint, error=error)

    def delete_entry(self, entry_id: str) -> None:
        with self._lock:
            self._get_entry(entry_id)
            del self._entries[entry_id]
            self._persist()

    def recoverable_entries(self) -> list[LedgerEntry]:
        return self.list_entries(status="running")

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
