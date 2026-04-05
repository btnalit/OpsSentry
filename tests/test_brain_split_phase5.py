import asyncio
import time
from pathlib import Path
from src.config_shield import ConfigShield, LockAcquisitionError

async def test_brain_split():
    print("=== [POC] ConfigShield Brain-Split / TTL Recovery Test ===")
    lock_dir = Path("data/test_locks_brain_split")
    if lock_dir.exists():
        import shutil
        shutil.rmtree(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    
    resource_id = "test_resource"
    ttl_ms = 1000 # 1 second TTL for fast test
    
    node_a = ConfigShield(node_id="node-a", lock_dir=lock_dir, ttl_ms=ttl_ms)
    node_b = ConfigShield(node_id="node-b", lock_dir=lock_dir, ttl_ms=ttl_ms)
    
    # 1. Node A acquires lock WITHOUT heartbeat
    print("[Node A] Acquiring lock (no heartbeat)...")
    node_a.acquire(resource_id, start_heartbeat=False)
    print("[Node A] Lock acquired.")
    
    # 2. Node B tries to acquire - should fail
    print("[Node B] Attempting to acquire lock while Node A holds it...")
    try:
        node_b.acquire(resource_id, start_heartbeat=False)
        print("[!] FAIL: Node B acquired lock while Node A held it.")
    except LockAcquisitionError as e:
        print(f"[-] Node B expected failure: {e}")
        
    # 3. Wait for TTL to expire
    print(f"Waiting {ttl_ms/1000 + 0.5}s for TTL to expire...")
    time.sleep(ttl_ms/1000 + 0.5)
    
    # 4. Node B acquires lock - should succeed due to stale recovery
    print("[Node B] Attempting to acquire lock after Node A's TTL expired...")
    try:
        node_b.acquire(resource_id, start_heartbeat=False)
        print("[-] Node B successfully acquired stale lock (PASS).")
    except LockAcquisitionError as e:
        print(f"[!] FAIL: Node B failed to acquire stale lock: {e}")
        
    # 5. Node A tries to heartbeat - should fail
    print("[Node A] Attempting to heartbeat now that Node B owns the lock...")
    try:
        node_a.heartbeat(resource_id)
        print("[!] FAIL: Node A successfully heartbeated after Node B took over.")
    except LockAcquisitionError as e:
        print(f"[-] Node A expected failure on heartbeat: {e}")
        
    # 6. Final verification
    inspect = node_b.inspect(resource_id)
    if inspect and inspect.node_id == "node-b":
        print("[-] Final state: Node B owns the lock (PASS).")
    else:
        print(f"[!] FAIL: Unexpected final owner: {inspect.node_id if inspect else 'None'}")

if __name__ == "__main__":
    asyncio.run(test_brain_split())
