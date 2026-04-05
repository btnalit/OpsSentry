import sys
import os
import asyncio
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.sandbox import DirectRunner, create_sandbox_provider

async def test_direct_runner():
    print("Testing DirectRunner...")
    runner = DirectRunner()
    
    # 1. Basic command
    res = await runner.execute("echo 'hello world'")
    assert res.exit_code == 0
    assert "hello world" in res.stdout
    print("Basic command passed")
    
    # 2. Timeout
    res = await runner.execute("python -c \"import time; time.sleep(10)\"", timeout_seconds=1)
    assert res.exit_code == 124
    print("Timeout passed")
    
    # 3. Environment Sanitization
    os.environ["SECRET_KEY"] = "super-secret"
    res = await runner.execute("echo $SECRET_KEY")
    # In DirectRunner, we sanitize env, so $SECRET_KEY should be empty
    assert "super-secret" not in res.stdout
    print("Environment sanitization passed")
    
    # 4. Truncation
    runner_small = DirectRunner(stdout_limit=10)
    res = await runner_small.execute("echo 'this is a long string'")
    assert res.truncated == True
    assert len(res.stdout) <= 10
    print("Truncation passed")

async def test_factory():
    print("Testing create_sandbox_provider...")
    # Default should be direct on Windows
    runner = create_sandbox_provider()
    assert runner.mode_name() == "direct"
    
    # Explicit override
    os.environ["SANDBOX_MODE"] = "direct"
    runner2 = create_sandbox_provider()
    assert runner2.mode_name() == "direct"
    print("Factory passed")

async def main():
    try:
        await test_direct_runner()
        await test_factory()
        print("\nAll SandboxProvider smoke tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
