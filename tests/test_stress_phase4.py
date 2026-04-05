import sys
import os
sys.path.insert(0, os.getcwd())

import asyncio
import json
import logging
import time
import random
import string
from fastapi.testclient import TestClient
from src.main import app

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StressTester")

def test_handshake_invalid_json():
    print("\n--- [Audit] Handshake Invalid JSON ---")
    client = TestClient(app)
    with client.websocket_connect("/api/sessions/chat") as websocket:
        websocket.send_text("not a json")
        try:
            resp = websocket.receive_text()
            data = json.loads(resp)
            if data.get("type") == "error":
                print(f"[-] Correctly handled invalid JSON: {data.get('message')}")
            else:
                print(f"[!] Unexpected response: {resp}")
        except Exception as e:
            print(f"[!] Crashed on invalid JSON: {e}")

def test_handshake_missing_ids():
    print("\n--- [Audit] Handshake Missing UID/DID ---")
    client = TestClient(app)
    with client.websocket_connect("/api/sessions/chat") as websocket:
        websocket.send_text(json.dumps({"uid": "test_user"})) # Missing did
        resp = websocket.receive_text()
        print(f"[-] Response for missing DID: {resp}")
        
def test_handshake_large_payload():
    print("\n--- [Audit] Handshake Large Payload ---")
    client = TestClient(app)
    large_data = "a" * (1024 * 1024) # 1MB string
    with client.websocket_connect("/api/sessions/chat") as websocket:
        websocket.send_text(large_data)
        try:
            resp = websocket.receive_text()
            print(f"[-] Handled large payload: {resp[:100]}...")
        except Exception as e:
            print(f"[!] Large payload might have caused issues: {e}")

async def simulate_agent_session(session_id: int):
    print(f"Starting session {session_id}...")
    # Since TestClient is sync, we use it for logic verification.
    # For concurrent stress, real 'websockets' library or threading is needed.
    # However, to simulate 'typewriter' output and detect 'packet sticking',
    # we measure arrival time of chunks.
    
    # We'll use TestClient in a separate thread if needed, but for simplicity
    # let's try concurrent connections using TestClient context if it supports it.
    # (FastAPI TestClient's websocket_connect is synchronous and uses context manager).
    # To do concurrent IO, we'd normally use something like httpx or websockets.
    pass

def verify_typewriter_timing():
    print("\n--- [Audit] Typewriter Timing & Packet Sticking ---")
    client = TestClient(app)
    uid, did = "btnalit", "DID-001"
    
    # 1. Handshake
    try:
        with client.websocket_connect("/api/sessions/chat") as websocket:
            websocket.send_text(json.dumps({"uid": uid, "did": did}))
            
            # 2. Command
            websocket.send_text(json.dumps({"message": "Describe your purpose in 20 words."}))
            
            last_time = time.time()
            chunks = []
            print("Streaming logs: ", end="", flush=True)
            
            while True:
                resp = websocket.receive_text()
                current_time = time.time()
                gap = (current_time - last_time) * 1000 # to ms
                last_time = current_time
                
                data = json.loads(resp)
                msg_type = data.get("type", "unknown")
                print(".", end="", flush=True)
                
                # We store data + gap (ms)
                chunks.append((msg_type, gap))
                
                if msg_type == "message" or msg_type == "error":
                    break
            
            print(" [DONE]")
            
            # 3. Analytics
            total_chunks = len(chunks)
            if total_chunks < 2:
                print(f"[!] Warning: Only {total_chunks} chunks received. Not enough data for jitter analysis.")
                return

            gaps = [g for t, g in chunks[1:]] # Skip first gap (handshake/think latency)
            avg_gap = sum(gaps) / len(gaps)
            max_gap = max(gaps)
            jitter = max_gap - avg_gap
            
            print(f"[-] Received {total_chunks} chunks.")
            print(f"[-] Avg Inter-chunk Gap: {avg_gap:.2f}ms")
            print(f"[-] Max Inter-chunk Gap: {max_gap:.2f}ms")
            print(f"[-] Jitter: {jitter:.2f}ms")
            
            if max_gap > 1000:
                print(f"[!] Critical: High latency gap ({max_gap:.2f}ms). UI will feel disconnected.")
            elif jitter > 200:
                print(f"[!] Warning: Jitter is high ({jitter:.2f}ms). Packet sticking potential.")
            else:
                print("[-] Performance: PASS (Smooth flow)")

    except Exception as e:
        print(f"[!] Test failed: {e}")

if __name__ == "__main__":
    test_handshake_invalid_json()
    test_handshake_missing_ids()
    test_handshake_large_payload()
    verify_typewriter_timing()
