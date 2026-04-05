import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.main import app
import shutil
import os

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "version" in response.json()
    print("Root endpoint test passed")

def test_agents_api():
    # Setup temp home
    temp_home = Path("temp_test_home")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["ACCIO_HOME"] = str(temp_home.absolute())
    
    # Reload dependencies to use new ACCIO_HOME
    from src import dependencies
    dependencies._manager = None
    dependencies._ledger = None
    dependencies.ACCIO_HOME = temp_home

    # 1. Create Agent
    payload = {
        "uid": "test_user",
        "name": "API Agent",
        "description": "Created via API",
        "vibe": "professional",
        "model_provider": "openai",
        "model_id": "gpt-4o"
    }
    response = client.post("/api/agents/", json=payload)
    assert response.status_code == 200
    did = response.json()["did"]
    print(f"Agent creation via API passed (DID: {did})")

    # 2. List Agents
    response = client.get("/api/agents/test_user")
    assert response.status_code == 200
    assert len(response.json()) == 1
    print("List agents via API passed")

    # 3. Get Agent
    response = client.get(f"/api/agents/test_user/{did}")
    assert response.status_code == 200
    assert response.json()["name"] == "API Agent"
    print("Get agent details via API passed")

    # Clean up
    if temp_home.exists():
        shutil.rmtree(temp_home)
    print("Cleanup passed")

def test_ledger_api():
    response = client.get("/api/ops/ledger/")
    assert response.status_code == 200
    print("Ledger list via API passed")

if __name__ == "__main__":
    try:
        test_root()
        test_agents_api()
        test_ledger_api()
        print("\nAll FastAPI routing tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
