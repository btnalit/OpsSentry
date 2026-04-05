import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app
import uuid

@pytest.mark.asyncio
async def test_cron_job_idor_prevention():
    """
    Test that a user cannot delete another user's cron job.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        user_a = "user_a"
        user_b = "user_b"
        
        # 1. User B creates a job
        job_id = f"job_{uuid.uuid4().hex}"
        create_payload = {
            "id": job_id,
            "name": "B's Job",
            "uid": user_b,
            "schedule": {"kind": "cron", "expr": "0 0 * * *"},
            "payload": {"kind": "command", "command": "echo hello"}
        }
        resp = await ac.post("/api/cron/jobs/", json=create_payload, headers={"X-User-ID": user_b})
        assert resp.status_code == 200, f"Failed to create job: {resp.text}"
        
        # 2. User A tries to delete User B's job
        delete_resp = await ac.delete(f"/api/cron/jobs/{job_id}", params={"uid": user_b}, headers={"X-User-ID": user_a})
        assert delete_resp.status_code == 403, "User A should NOT be able to delete User B's job"
        
        # 3. Verify job still exists for User B
        get_resp = await ac.get(f"/api/cron/jobs/{job_id}", params={"uid": user_b}, headers={"X-User-ID": user_b})
        assert get_resp.status_code == 200, "Job should still exist for User B"

@pytest.mark.asyncio
async def test_agent_manager_idor_prevention():
    """
    Test that a user cannot access another user's agent core files.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        user_a = "user_a"
        user_b = "user_b"
        did = "DID-B-1"
        
        # Create agent for user_b
        create_payload = {
            "uid": user_b,
            "did": did,
            "name": "B's Agent",
            "description": "B's Agent",
            "vibe": "expert",
            "model_provider": "openai",
            "model_id": "gpt-4"
        }
        await ac.post("/api/agents/", json=create_payload, headers={"X-User-ID": user_b})
        
        # User A tries to read User B's SOUL.md
        read_resp = await ac.get(f"/api/agents/{user_b}/{did}/core/SOUL.md", headers={"X-User-ID": user_a})
        assert read_resp.status_code == 403, "User A should be blocked from reading User B's SOUL.md"
        print("\n[-] Agent IDOR Blocked: User A cannot read User B's core files (X-User-ID check passed)")
