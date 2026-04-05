from src.ops_ledger import OpsLedger
from pathlib import Path
import os

def test_ledger_v2():
    db_path = Path("data/ops-queue/ledger_test.db")
    # Clean up previous test runs
    for f in db_path.parent.glob(f"{db_path.name}*"):
        try:
            f.unlink()
        except:
            pass
    
    print(f"Initializing ledger at {db_path}...")
    ledger = OpsLedger(db_path)
    
    print("Creating entry...")
    entry = ledger.create_entry("test_action", metadata={"foo": "bar"})
    print(f"Created entry ID: {entry.id}")
    assert entry.action == "test_action"
    assert entry.status == "pending"
    assert entry.metadata == {"foo": "bar"}
    
    print("Transitioning to running...")
    ledger.mark_running(entry.id, checkpoint={"progress": 50})
    entry = ledger.get_entry(entry.id)
    print(f"Status: {entry.status}, Checkpoint: {entry.checkpoint}")
    assert entry.status == "running"
    assert entry.checkpoint == {"progress": 50}
    
    print("Transitioning to completed...")
    ledger.mark_completed(entry.id)
    entry = ledger.get_entry(entry.id)
    print(f"Status: {entry.status}")
    assert entry.status == "completed"
    
    print("Listing entries...")
    entries = ledger.list_entries()
    print(f"Total entries: {len(entries)}")
    assert len(entries) == 1
    
    print("Testing status filtering...")
    completed_entries = ledger.list_entries(status="completed")
    assert len(completed_entries) == 1
    pending_entries = ledger.list_entries(status="pending")
    assert len(pending_entries) == 0
    
    print("Cleaning up...")
    # Close connections before unlinking (sqlite3 connections might hold locks)
    # In our implementation, we use threading.local() so we can't easily close all.
    # But this is a test script, we'll try our best.
    
    # Actually, for the test, we can just leave it or use a separate process.
    print("Test passed!")

if __name__ == "__main__":
    try:
        test_ledger_v2()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
