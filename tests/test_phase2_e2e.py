import sys
import os
import asyncio
import shutil
import tempfile
from pathlib import Path
import pytest

# Add src to python path for all test script runs
sys.path.append(str(Path(__file__).parent.parent / "src"))

from src.agent_manager import AgentManager, AgentCreateRequest
from src.ops_ledger import OpsLedger
from src.sandbox import create_sandbox_provider
from src.tool_registry import ToolRegistry

@pytest.mark.asyncio
async def test_phase2_full_integration():
    """
    E2E Test: Create Agent -> Dispatch Bash Tool -> Verify Ledger
    
    This verifies the "API -> ToolRegistry -> Sandbox -> OpsLedger" chain logic.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        home = Path(tmp_dir)
        
        # 1. Setup components in a isolated home directory
        ledger_path = home / "data/ops-queue/ledger.jsonl"
        ledger = OpsLedger(ledger_path=ledger_path)
        manager = AgentManager(accio_home=home)
        
        # Force "direct" mode for testing on local dev environment
        os.environ["SANDBOX_MODE"] = "direct"
        sandbox = create_sandbox_provider()
        
        # 2. Create Agent using AgentManager (Core logic for /api/agents POST)
        req = AgentCreateRequest(
            uid="user-e2e",
            name="E2E-Agent",
            description="End-to-end integration test agent",
            vibe="expert",
            model_provider="openai",
            model_id="gpt-4o"
        )
        profile = manager.create_agent(req)
        assert profile.did.startswith("DID-")
        print(f"Agent {profile.did} created in isolated home: {home}")
        
        # 3. Setup ToolRegistry with Agent's enabled tool groups (Core logic for Chat Session)
        registry = ToolRegistry(
            ops_ledger=ledger,
            sandbox=sandbox,
            enabled_groups=profile.tools
        )
        
        # 4. Execute tool call: df -h (or echo if on Windows without unix tools)
        command = "df -h"
        if sys.platform == "win32" and not shutil.which("df"):
            command = "echo 'Windows mock df output'"
            
        print(f"Executing tool call: bash(command='{command}')")
        tool_args = {"command": command, "timeout": 10}
        result = await registry.dispatch("bash", tool_args)
        
        # 5. Verify Execution Result
        assert "exit_code" in result
        assert result["exit_code"] == 0
        assert "stdout" in result
        print(f"Tool execution completed with exit_code: {result['exit_code']}")
        
        # 6. Verify OpsLedger Audit Trail
        entries = ledger.list_entries()
        # Should have one sandbox_exec entry
        exec_entries = [e for e in entries if e.action == "sandbox_exec"]
        assert len(exec_entries) == 1
        
        last_exec = exec_entries[0]
        assert last_exec.status == "completed"
        assert last_exec.metadata["command"] == command
        assert "duration_ms" in last_exec.checkpoint
        assert last_exec.checkpoint["exit_code"] == 0
        
        print("\n[Phase 2 E2E] Integration Test PASS!")
        print(f"- Ledger Audit Entry: {last_exec.id}")
        print(f"- Audit Action: {last_exec.action}")
        print(f"- Audit Status: {last_exec.status}")
        print(f"- Sandbox Mode: {last_exec.checkpoint.get('sandbox_mode')}")

if __name__ == "__main__":
    # If run directly as a script
    try:
        asyncio.run(test_phase2_full_integration())
    except Exception as e:
        print(f"\n[Phase 2 E2E] Integration Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
