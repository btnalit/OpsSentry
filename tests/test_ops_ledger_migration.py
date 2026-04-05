import json
from pathlib import Path
from src.ops_ledger import OpsLedger, DEFAULT_LEDGER_PATH, OLD_LEDGER_PATH
import os

def test_migration():
    print("Setting up migration test...")
    # Setup mock jsonl
    OLD_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OLD_LEDGER_PATH.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "old-1", "action": "migrate_me", "status": "completed", "created_at": 1000, "updated_at": 2000}) + "\n")
    
    # Ensure no existing DB
    if DEFAULT_LEDGER_PATH.exists():
        DEFAULT_LEDGER_PATH.unlink()
    # Also clean up WAL files
    for f in DEFAULT_LEDGER_PATH.parent.glob(f"{DEFAULT_LEDGER_PATH.name}*"):
        try: f.unlink()
        except: pass
    
    print("Initializing ledger (should trigger migration)...")
    ledger = OpsLedger()
    
    # Verify entry exists
    try:
        entry = ledger.get_entry("old-1")
        print(f"Migrated entry found: {entry.id}, Action: {entry.action}")
        assert entry.action == "migrate_me"
    except Exception as e:
        print(f"Migration failed: Entry not found or error: {e}")
        raise
    
    # Verify old file was renamed
    bak_path = OLD_LEDGER_PATH.with_suffix(".jsonl.bak")
    print(f"Checking if {OLD_LEDGER_PATH} was renamed to {bak_path}...")
    assert not OLD_LEDGER_PATH.exists()
    assert bak_path.exists()
    
    print("Migration test passed!")
    
    # Cleanup
    try:
        if DEFAULT_LEDGER_PATH.exists():
            DEFAULT_LEDGER_PATH.unlink()
        for f in DEFAULT_LEDGER_PATH.parent.glob(f"{DEFAULT_LEDGER_PATH.name}*"):
            try: f.unlink()
            except: pass
        if bak_path.exists():
            bak_path.unlink()
    except Exception as e:
        print(f"Cleanup error: {e}")

if __name__ == "__main__":
    try:
        test_migration()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
