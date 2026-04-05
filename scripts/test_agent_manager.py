import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import shutil
import tempfile
from src.agent_manager import AgentManager, AgentCreateRequest

def test_agent_manager():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        manager = AgentManager(accio_home=home)
        
        # 1. Create agent
        req = AgentCreateRequest(
            uid="user123",
            name="Test Agent",
            description="Testing agent manager",
            vibe="professional",
            model_provider="openai",
            model_id="gpt-4o"
        )
        profile = manager.create_agent(req)
        print(f"Created agent: {profile.did}")
        
        # 2. Check directory structure
        core_dir = home / "accounts" / "user123" / "agents" / profile.did / "agent-core"
        assert core_dir.exists()
        assert (core_dir / "agent_config.json").exists()
        assert (core_dir / "tool-registry.jsonc").exists()
        assert (core_dir / "SOUL.md").exists()
        assert (core_dir / "skills").is_dir()
        
        # 3. Read core file
        soul = manager.read_core_file("user123", profile.did, "SOUL.md")
        assert "Test Agent SOUL" in soul
        
        # 4. Update agent
        manager.update_agent("user123", profile.did, {"name": "Updated Agent"})
        profile_updated = manager.get_agent("user123", profile.did)
        assert profile_updated.name == "Updated Agent"
        
        # 5. List agents
        agents = manager.list_agents("user123")
        assert len(agents) == 1
        assert agents[0].did == profile.did
        
        # 6. Bind skill
        manager.bind_skill("user123", profile.did, "log-analyzer")
        profile_skill = manager.get_agent("user123", profile.did)
        assert "log-analyzer" in profile_skill.skills
        
        # 7. Unbind skill
        manager.unbind_skill("user123", profile.did, "log-analyzer")
        profile_no_skill = manager.get_agent("user123", profile.did)
        assert "log-analyzer" not in profile_no_skill.skills
        
        # 8. Delete agent
        manager.delete_agent("user123", profile.did)
        assert not (home / "accounts" / "user123" / "agents" / profile.did).exists()
        
        print("All AgentManager tests passed!")

if __name__ == "__main__":
    test_agent_manager()
