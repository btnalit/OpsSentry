from __future__ import annotations

import time

from src.config_shield import ConfigShield, LockAcquisitionError
from src.global_sync import SyncBuffer, SyncEnvelope
from src.knowledge_core import KnowledgeCore
from src.ops_ledger import LedgerStateError, OpsLedger


def test_ops_ledger_persists_and_recovers(tmp_path):
    ledger_path = tmp_path / "data" / "ops-queue" / "ledger.jsonl"
    ledger = OpsLedger(ledger_path)

    entry = ledger.create_entry(
        "restart_nginx",
        entry_id="task-1",
        accio_task_ref="ACCIO-1",
        checkpoint={"step": 1},
    )
    assert entry.status == "pending"

    ledger.mark_running(entry.id, checkpoint={"step": 2, "last_output": "reload started"})
    recovered = OpsLedger(ledger_path)
    running = recovered.recoverable_entries()

    assert len(running) == 1
    assert running[0].id == "task-1"
    assert running[0].checkpoint["step"] == 2

    recovered.mark_completed("task-1", checkpoint={"step": 3})
    final_entry = OpsLedger(ledger_path).get_entry("task-1")
    assert final_entry.status == "completed"
    assert final_entry.checkpoint["step"] == 3


def test_knowledge_core_searches_markdown_chunks(tmp_path):
    knowledge_dir = tmp_path / "data" / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "runbook.md").write_text(
        "# Runbook\n\n## Nginx reload failed\npriority_score: 2.0\nUse nginx -t before reload.\n\n## Disk full\nRotate logs first.\n",
        encoding="utf-8",
    )

    engine = KnowledgeCore(knowledge_dir)
    hits = engine.search("nginx reload", limit=3)

    assert hits
    assert hits[0].chunk.heading == "Nginx reload failed"
    assert "nginx" in hits[0].terms


def test_config_shield_reclaims_stale_lock(tmp_path):
    lock_dir = tmp_path / "data" / "locks"
    shield_a = ConfigShield("node-a", lock_dir=lock_dir, ttl_ms=100, heartbeat_interval_ms=1_000, on_lock_acquired=None)
    shield_b = ConfigShield("node-b", lock_dir=lock_dir, ttl_ms=100, heartbeat_interval_ms=1_000, on_lock_acquired=None)

    shield_a.acquire("/etc/nginx/nginx.conf", start_heartbeat=False)
    with _AssertRaises(LockAcquisitionError):
        shield_b.acquire("/etc/nginx/nginx.conf", start_heartbeat=False)

    time.sleep(0.15)
    record = shield_b.acquire("/etc/nginx/nginx.conf", start_heartbeat=False)
    assert record.node_id == "node-b"


def test_sync_buffer_appends_messages(tmp_path):
    buffer_path = tmp_path / "data" / "ops-queue" / "sync-buffer.jsonl"
    buffer = SyncBuffer(buffer_path)
    buffer.append(SyncEnvelope(node_id="SENTRY-01", msg_type="STATE_SYNC", payload={"status": "running"}))

    rows = buffer.read_all()
    assert len(rows) == 1
    assert rows[0]["schema_version"] == "1.0"
    assert rows[0]["msgType"] == "STATE_SYNC"
    assert buffer_path.stat().st_size > 0


def test_ops_ledger_rejects_invalid_terminal_transition(tmp_path):
    ledger_path = tmp_path / "data" / "ops-queue" / "ledger.jsonl"
    ledger = OpsLedger(ledger_path)
    ledger.create_entry("restart_nginx", entry_id="task-2")
    ledger.mark_running("task-2")
    ledger.mark_completed("task-2")

    with _AssertRaises(LedgerStateError):
        ledger.mark_running("task-2")


class _AssertRaises:
    def __init__(self, exc_type):
        self.exc_type = exc_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"expected {self.exc_type.__name__} to be raised")
        if not issubclass(exc_type, self.exc_type):
            return False
        return True
