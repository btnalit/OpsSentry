import multiprocessing
import time
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.getcwd())

from src.ops_ledger import OpsLedger
from src.ledger_entry import LedgerStateError, LedgerEntryNotFound

DB_PATH = Path("data/ops-queue/brain_split_test.db")

def setup_test_entry():
    if DB_PATH.exists():
        DB_PATH.unlink()
    
    ledger = OpsLedger(DB_PATH)
    entry = ledger.create_entry("CONCURRENCY_TEST", entry_id="test-1")
    print(f"Created entry: {entry.id}, status: {entry.status}")
    return entry.id

def worker_grab_task(proc_id, entry_id, results_queue):
    """Attempt to transition the task to 'running'"""
    try:
        ledger = OpsLedger(DB_PATH)
        # Simulation: high frequency overlap
        # Wait a tiny bit to increase chance of overlap
        time.sleep(0.1) 
        
        entry = ledger.mark_running(entry_id)
        results_queue.put((proc_id, True, "Success"))
    except LedgerStateError as e:
        results_queue.put((proc_id, False, str(e)))
    except Exception as e:
        results_queue.put((proc_id, False, f"Unexpected error: {e}"))

def run_brain_split_simulation():
    print("--- Starting Brain Split Simulation 2.0 (Cross-Process) ---")
    entry_id = setup_test_entry()
    
    results_queue = multiprocessing.Queue()
    processes = []
    
    # Spawn 10 processes to compete for the same entry
    for i in range(10):
        p = multiprocessing.Process(target=worker_grab_task, args=(i, entry_id, results_queue))
        processes.append(p)
        p.start()
        
    for p in processes:
        p.join()
        
    successes = []
    failures = []
    
    while not results_queue.empty():
        res = results_queue.get()
        if res[1]:
            successes.append(res)
        else:
            failures.append(res)
            
    print("-" * 30)
    print(f"Competing processes: 10")
    print(f"Successes (Transitioned to running): {len(successes)}")
    print(f"Failures (Blocked by state logic): {len(failures)}")
    
    for proc_id, _, msg in failures:
        # print(f"  Proc {proc_id} failed: {msg}")
        pass

    if len(successes) > 1:
        print("\n[AUDIT FAIL] BRAIN SPLIT DETECTED!")
        print(f"Multiple processes ({len(successes)}) believe they transitioned the task.")
    elif len(successes) == 1:
        print("\n[AUDIT PASS] Atomic state transition verified (or very lucky).")
    else:
        print("\n[AUDIT ERROR] No process succeeded.")

if __name__ == "__main__":
    run_brain_split_simulation()
