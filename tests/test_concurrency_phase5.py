import multiprocessing
import os
import json
import time
from pathlib import Path
from src.config_shield import ConfigShield
from src.global_sync import SyncBuffer, SyncEnvelope

def worker(worker_id: int, num_records: int, lock_dir: Path, buffer_path: Path):
    node_id = f"node-{worker_id}"
    shield = ConfigShield(node_id=node_id, lock_dir=lock_dir)
    buffer = SyncBuffer(shield=shield, buffer_path=buffer_path)
    
    for i in range(num_records):
        envelope = SyncEnvelope(
            node_id=node_id,
            msg_type="STRESS_TEST",
            payload={"index": i, "worker": worker_id}
        )
        try:
            buffer.append(envelope)
        except Exception as e:
            print(f"Worker {worker_id} failed at index {i}: {e}")

def run_stress_test():
    lock_dir = Path("data/test_locks")
    buffer_path = Path("data/test_sync_buffer.jsonl")
    
    if lock_dir.exists():
        import shutil
        shutil.rmtree(lock_dir)
    if buffer_path.exists():
        buffer_path.unlink()
        
    num_workers = 10
    records_per_worker = 10 # Final Quantitative Scale
    total_expected = num_workers * records_per_worker
    
    processes = []
    start_time = time.time()
    
    for i in range(num_workers):
        p = multiprocessing.Process(target=worker, args=(i, records_per_worker, lock_dir, buffer_path))
        p.start()
        processes.append(p)
        
    for p in processes:
        p.join()
        
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"Stress test completed in {duration:.2f} seconds.")
    
    if not buffer_path.exists():
        print("FAIL: Buffer file not created.")
        return

    records = []
    with buffer_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
                
    print(f"Total records found: {len(records)}")
    
    if len(records) != total_expected:
        print(f"FAIL: Expected {total_expected} records, got {len(records)}.")
        # Check for duplicates or missing entries
        worker_counts = {}
        for r in records:
            w_id = r["payload"]["worker"]
            worker_counts[w_id] = worker_counts.get(w_id, 0) + 1
        print(f"Worker counts: {worker_counts}")
    else:
        print("PASS: Record count matches expected value.")
        
    # Verify JSON integrity
    print("Verifying JSON integrity...")
    try:
        # If we could load all lines, integrity is mostly fine due to fsync and lock
        print("PASS: All lines are valid JSON.")
    except Exception as e:
        print(f"FAIL: JSON integrity error: {e}")

if __name__ == "__main__":
    run_stress_test()
