import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add src to python path
sys.path.append(str(Path(__file__).parent.parent))

from src.agent_manager import AgentManager, AgentCreateRequest
from src.agent_vm import create_agent_vm
from src import dependencies

async def test_agent_vm():
    print("Testing AgentVM initialization and prompt assembly...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        dependencies.ACCIO_HOME = home
        
        # 1. Setup Agent
        manager = dependencies.get_agent_manager()
        req = AgentCreateRequest(
            uid="user1",
            name="VM-Test-Agent",
            description="Testing VM prompt assembly",
            vibe="expert",
            model_provider="openai",
            model_id="gpt-4o",
            core_files={
                "SOUL.md": "I am a test agent soul.",
                "IDENTITY.md": "I am a test identity."
            }
        )
        profile = manager.create_agent(req)
        did = profile.did
        print(f"Agent {did} created.")

        # 2. Create VM
        vm = create_agent_vm("user1", did)
        
        # 3. Test prompt assembly
        system_prompt = await vm._assemble_system_prompt()
        print("\n--- Assembled System Prompt ---")
        print(system_prompt)
        print("-------------------------------\n")
        
        assert "I am a test agent soul." in system_prompt
        assert "I am a test identity." in system_prompt
        assert "## AVAILABLE TOOLS" in system_prompt
        assert "## SYSTEM GUIDELINES" in system_prompt
        
        # 4. Mock chat (without real API call if possible, or just test loop)
        # Note: litellm requires API keys, so we only test assembly for now
        # unless we mock litellm.acompletion.
        
        print("AgentVM prompt assembly test passed!")

if __name__ == "__main__":
    asyncio.run(test_agent_vm())
