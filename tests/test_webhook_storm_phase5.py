import asyncio
import time
import os
from pathlib import Path
from src.dependencies import get_message_router, get_ops_ledger, get_sync_buffer
from src.global_sync import SyncEnvelope

async def simulate_webhook_storm():
    print("=== [POC] Webhook Storm & Ledger Concurrency Test ===")
    router = get_message_router()
    ledger = get_ops_ledger()
    sync_buffer = get_sync_buffer()
    
    # Clear ledger and sync buffer
    if ledger.ledger_path.exists():
        ledger.ledger_path.unlink()
    ledger._entries = {}
    sync_buffer.clear()
    
    num_webhooks = 500
    print(f"Simulating {num_webhooks} concurrent webhooks (Ledger vs SyncBuffer)...")
    
    # Test 1: OpsLedger (O(N^2) write)
    start_time = time.perf_counter()
    tasks = [router.route_message("u1", "s1", f"dev-{i}", f"msg {i} @DID-12345678-ABCDEF") for i in range(num_webhooks)]
    await asyncio.gather(*tasks)
    ledger_duration = time.perf_counter() - start_time
    print(f"OpsLedger: {num_webhooks} writes took {ledger_duration:.2f}s")
    
    # Test 2: SyncBuffer (O(N) write - Append-only)
    start_time = time.perf_counter()
    sync_tasks = []
    for i in range(num_webhooks):
        envelope = SyncEnvelope(node_id="test-node", msg_type="audit", payload={"idx": i, "content": "storm"})
        sync_tasks.append(asyncio.to_thread(sync_buffer.append, envelope))
    await asyncio.gather(*sync_tasks)
    sync_duration = time.perf_counter() - start_time
    print(f"SyncBuffer (LockedSyncBuffer): {num_webhooks} writes took {sync_duration:.2f}s")
    
    # Validation
    print(f"Final Ledger: {len(ledger)}, SyncBuffer: {len(sync_buffer.read_all())}")
    
    if sync_duration < ledger_duration:
         print(f"[-] Performance: SyncBuffer is {ledger_duration/sync_duration:.1f}x faster (PASS).")
    else:
         print(f"[!] Performance: SyncBuffer is unexpectedly slower than Ledger.")

if __name__ == "__main__":
    asyncio.run(simulate_webhook_storm())
