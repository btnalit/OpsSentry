import sqlite3
import time
import multiprocessing
import os
import random
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.getcwd())

from src.ops_ledger import OpsLedger

DB_PATH = Path("concurrency_audit.db")
TOTAL_RECORDS = 500
CONCURRENT_PROCESSES = 5
RECORDS_PER_PROCESS = TOTAL_RECORDS // CONCURRENT_PROCESSES

def setup_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    ledger = OpsLedger(DB_PATH)
    print(f"Audit DB Initialized at {DB_PATH}")

def worker_audit(proc_id, count):
    """Simulate high-frequency writes and monitor locks"""
    ledger = OpsLedger(DB_PATH)
    
    success_count = 0
    locked_count = 0
    
    for i in range(count):
        try:
            entry_id = f"audit-{proc_id}-{i}-{random.getrandbits(32)}"
            ledger.create_entry("CONCURRENCY_AUDIT", entry_id=entry_id)
            success_count += 1
        except Exception as e:
            if "database is locked" in str(e).lower():
                locked_count += 1
            else:
                print(f"Proc {proc_id}: Unexpected error: {e}")
    
    if locked_count > 0:
        print(f"Proc {proc_id}: {locked_count} locks encountered.")

def run_concurrency_audit(num_procs=None, num_records=None):
    num_procs = num_procs or CONCURRENT_PROCESSES
    num_records = num_records or RECORDS_PER_PROCESS
    total_expected = num_procs * num_records
    
    print(f"--- Starting SQLite Concurrency Performance Audit ---")
    print(f"Processes: {num_procs}, Records per Proc: {num_records}, Expected: {total_expected}")
    setup_db()
    
    processes = []
    
    start_total = time.time()
    for i in range(num_procs):
        p = multiprocessing.Process(target=worker_audit, args=(i, num_records))
        processes.append(p)
        p.start()
        
    for p in processes:
        p.join()
        
    duration = time.time() - start_total
    
    # 最终结果审计
    conn = sqlite3.connect(str(DB_PATH))
    count = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    conn.close()
    
    print("-" * 30)
    print(f"Total Successful Writes: {count}")
    print(f"Overall Duration: {duration:.2f}s")
    print(f"Average Throughput: {count / duration:.2f} records/s")
    
    if count == total_expected:
        print("[AUDIT PASS] All records written successfully.")
    else:
        print(f"[AUDIT NOTE] Data loss detected due to locks! Expected {total_expected}, got {count}")

if __name__ == "__main__":
    # Test with high concurrency
    run_concurrency_audit(num_procs=20, num_records=500)
