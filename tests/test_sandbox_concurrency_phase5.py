import asyncio
import time
import os
from src.sandbox import create_sandbox_provider

async def test_sandbox_concurrency():
    print("=== [POC] Sandbox Bounded Concurrency Test ===")
    os.environ["SANDBOX_MAX_CONCURRENCY"] = "3" # Limit to 3
    provider = create_sandbox_provider(mode="direct")
    
    start_time = time.perf_counter()
    
    # Run 6 tasks, each taking 1 second
    # Expected: 2 batches of 3 tasks = ~2 seconds total
    tasks = []
    for i in range(6):
        # We use a command that sleeps for 1 second
        cmd = "python -c \"import time; time.sleep(1)\""
        tasks.append(provider.execute(cmd))
    
    print(f"Launching 6 sandbox tasks (limit=3, task_duration=1s)...")
    results = await asyncio.gather(*tasks)
    
    total_duration = time.perf_counter() - start_time
    print(f"Total time taken: {total_duration:.2f}s")
    
    # Validation
    if 1.8 <= total_duration <= 2.5:
        print("[-] Sandbox Bounded Execution PASS (Tasks queued correctly).")
    else:
        print(f"[!] Sandbox Bounded Execution FAIL (Duration {total_duration:.2f}s out of expected ~2s).")

if __name__ == "__main__":
    asyncio.run(test_sandbox_concurrency())
