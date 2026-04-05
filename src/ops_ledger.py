from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .ledger_entry import (
    LedgerEntry,
    LedgerEntryNotFound,
    LedgerStateError,
    utc_ms,
    VALID_STATUSES,
    VALID_TRANSITIONS,
)
from .sqlite_ledger_storage import ILedgerStorage, SQLiteLedgerStorage

DEFAULT_LEDGER_PATH = Path("data/ops-queue/ledger.db")
OLD_LEDGER_PATH = Path("data/ops-queue/ledger.jsonl")


class OpsLedger:
    def __init__(self, ledger_path: str | Path = DEFAULT_LEDGER_PATH) -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.storage: ILedgerStorage = SQLiteLedgerStorage(self.ledger_path)
        
        # Migration logic
        if self.ledger_path == DEFAULT_LEDGER_PATH:
            self._migrate_from_jsonl(OLD_LEDGER_PATH)

    def _migrate_from_jsonl(self, jsonl_path: Path) -> None:
        if not jsonl_path.exists():
            return
        
        # Check if already migrated
        if self.storage.count() > 0:
            return

        print(f"Migrating OpsLedger from {jsonl_path} to SQLite (Spec-aligned)...")
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    entry = LedgerEntry.from_record(record)
                    self.storage.append(entry)
                except Exception as e:
                    print(f"Failed to migrate record from JSONL: {e}")
        
        # Rename old file
        try:
            bak_path = jsonl_path.with_suffix(".jsonl.bak")
            if bak_path.exists():
                bak_path.unlink()
            jsonl_path.rename(bak_path)
            print("Migration complete.")
        except Exception as e:
            print(f"Failed to rename old ledger file: {e}")

    def create_entry(
        self,
        action: str,
        *,
        entry_id: str | None = None,
        accio_ref: str | None = None,
        checkpoint: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        with self._lock:
            identifier = entry_id or str(uuid.uuid4())
            if self.storage.get(identifier):
                raise LedgerStateError(f"duplicate ledger id: {identifier}")

            entry = LedgerEntry(
                id=identifier,
                action=action,
                status="pending",
                checkpoint=dict(checkpoint or {}),
                accio_ref=accio_ref,
                metadata=dict(metadata or {}),
            )
            self.storage.append(entry)
            return self.get_entry(entry.id)

    def list_entries(self, *, status: str | None = None, limit: int = 1000) -> list[LedgerEntry]:
        with self._lock:
            return self.storage.list_all(status=status, limit=limit)

    def get_entry(self, entry_id: str) -> LedgerEntry:
        with self._lock:
            entry = self.storage.get(entry_id)
            if not entry:
                raise LedgerEntryNotFound(entry_id)
            return entry

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
            # Atomic transition logic
            # Find which old statuses allow this new status.
            allowed_old_statuses = [
                old_s for old_s, new_s_set in VALID_TRANSITIONS.items()
                if status in new_s_set
            ]
            
            updates: dict[str, Any] = {
                "status": status,
                "updated_at": utc_ms()
            }
            if checkpoint is not None:
                updates["checkpoint"] = dict(checkpoint)
            if error is not None:
                updates["last_error"] = error
            elif status != "failed":
                updates["last_error"] = None
            
            success = self.storage.update(entry_id, updates, expected_statuses=allowed_old_statuses)
            if not success:
                entry = self.storage.get(entry_id)
                if not entry:
                    raise LedgerEntryNotFound(entry_id)
                raise LedgerStateError(f"invalid transition: {entry.status} -> {status} (possibly already updated by another agent)")
            
            return self.get_entry(entry_id)

    def mark_running(self, entry_id: str, *, checkpoint: dict[str, Any] | None = None) -> LedgerEntry:
        return self.transition(entry_id, "running", checkpoint=checkpoint)

    def update_checkpoint(self, entry_id: str, checkpoint: dict[str, Any]) -> LedgerEntry:
        with self._lock:
            # Checkpoint update also needs to be atomic or at least check status
            # Only allowed in pending/running
            updates = {
                "checkpoint": dict(checkpoint),
                "updated_at": utc_ms()
            }
            success = self.storage.update(entry_id, updates, expected_statuses=["pending", "running"])
            if not success:
                entry = self.storage.get(entry_id)
                if not entry:
                    raise LedgerEntryNotFound(entry_id)
                raise LedgerStateError(f"cannot checkpoint entry in status {entry.status}")
            
            return self.get_entry(entry_id)

    def mark_completed(self, entry_id: str, *, checkpoint: dict[str, Any] | None = None) -> LedgerEntry:
        return self.transition(entry_id, "completed", checkpoint=checkpoint)

    def mark_failed(self, entry_id: str, error: str, *, checkpoint: dict[str, Any] | None = None) -> LedgerEntry:
        entry = self.transition(entry_id, "failed", checkpoint=checkpoint, error=error)
        
        # Emit Alert (Phase 8 #72)
        try:
            from src.cluster.alert_engine import AlertEvent
            from src.dependencies import get_alert_aggregator
            import asyncio
            
            event = AlertEvent(
                type="TASK_FAILED",
                severity="WARNING",
                source=f"agent:{entry.accio_ref}" if entry.accio_ref else "system",
                message=f"Task {entry.action} failed: {error}",
                details={"entry_id": entry.id, "action": entry.action, "error": error}
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(get_alert_aggregator().emit(event))
            except RuntimeError:
                asyncio.run(get_alert_aggregator().emit(event))
        except Exception as ae:
            # We don't want to fail the ledger update if alert fails
            pass

        return entry

    def delete_entry(self, entry_id: str) -> None:
        with self._lock:
            self.get_entry(entry_id)
            self.storage.delete(entry_id)

    def recoverable_entries(self) -> list[LedgerEntry]:
        return self.list_entries(status="running")

    def __len__(self) -> int:
        with self._lock:
            return len(self.storage.count())
