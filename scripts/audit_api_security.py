import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_idor_agents():
    print("=== [AUDIT] API IDOR Test (Agents) ===")
    # Scenario: User A tries to access User B's agents
    user_a = "user_a"
    user_b = "user_b"
    
    # Create agent for User B
    payload = {
        "uid": user_b,
        "did": "did_b_1",
        "name": "Agent B",
        "description": "B's Agent",
        "vibe": "expert",
        "model_provider": "openai",
        "model_id": "gpt-4"
    }
    requests.post(f"{BASE_URL}/agents/", json=payload)
    
    # User A tries to list User B's agents
    resp = requests.get(f"{BASE_URL}/agents/{user_b}")
    if resp.status_code == 200:
        print(f"[!] IDOR Detected: User A can list User B's agents. Data: {resp.json()}")
    else:
        print(f"[-] IDOR Blocked (Status: {resp.status_code})")

def test_path_traversal_core_files():
    print("\n=== [AUDIT] Path Traversal Test (Core Files) ===")
    user = "audit_user"
    did = "did_audit_1"
    
    # Try to read outside agent directory
    traversal_filenames = [
        "../../../../../../etc/passwd",
        "..\\..\\..\\..\\..\\windows\\win.ini",
        "../config_shield.py"
    ]
    
    for filename in traversal_filenames:
        resp = requests.get(f"{BASE_URL}/agents/{user}/{did}/core/{filename}")
        if resp.status_code == 200:
            print(f"[!] Traversal Successful: Read {filename}. Snippet: {str(resp.json())[:100]}")
        else:
            print(f"[-] Traversal Blocked for {filename} (Status: {resp.status_code})")

def test_cron_injection():
    print("\n=== [AUDIT] Cron Injection & IDOR Test ===")
    # Try to create a cron job for another user
    malicious_job = {
        "name": "Malicious Wipe",
        "uid": "victim_user",
        "schedule": {"kind": "cron", "expr": "* * * * *"},
        "payload": {"kind": "command", "command": "rm -rf /data/victim_files"}
    }
    resp = requests.post(f"{BASE_URL}/cron/jobs/", json=malicious_job)
    if resp.status_code == 200:
        print(f"[!] Cron Injection: Successfully created job for victim_user. ID: {resp.json().get('id')}")
    else:
        print(f"[-] Cron Injection Blocked (Status: {resp.status_code})")

if __name__ == "__main__":
    print("Note: API server must be running at http://localhost:8000")
    try:
        test_idor_agents()
        test_path_traversal_core_files()
        test_cron_injection()
    except Exception as e:
        print(f"Error connecting to API: {e}")
