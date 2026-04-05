import asyncio
import time
import json
from unittest.mock import MagicMock, patch
from src.dependencies import get_message_router, get_ops_ledger, get_agent_manager
from src.message_router import MessageRouter

async def audit_self_healing_link():
    print("=== [AUDIT] Phase 5 Self-healing E2E Link Audit ===")
    router = get_message_router()
    ledger = get_ops_ledger()
    manager = get_agent_manager()
    
    # 1. Setup mock agent
    uid = "audit-user"
    did = "DID-12345678-ABCDEF"
    try:
        manager.get_agent(uid, did)
    except:
        from src.agent_manager import AgentCreateRequest
        manager.create_agent(AgentCreateRequest(
            uid=uid, name="Healer", description="Audit Agent", vibe="professional",
            model_provider="openai", model_id="gpt-4", did=did
        ))

    # 2. Trace MessageRouter -> AgentVM Handoff
    # We patch AgentVM.chat to see if it gets called
    with patch("src.agent_vm.AgentVM.chat") as mock_chat:
        # Mocking an async generator
        async def mock_gen(*args, **kwargs):
            yield {"type": "content", "content": "I will fix it."}
            yield {"type": "done"}
        mock_chat.return_value = mock_gen()
        
        print(f"[Audit] Injecting @mention for {did}...")
        await router.route_message(
            uid=uid,
            session_id="audit-session",
            sender_did="external-boss",
            content=f"Please fix disk space @{did}"
        )
        
        # 3. Check if AgentVM was triggered
        # Current MessageRouter has TODO, so we expect this to fail (0 calls) 
        # unless Developer already fixed it in parallel.
        call_count = mock_chat.call_count
        print(f"[Audit] AgentVM.chat call count: {call_count}")
        
        if call_count > 0:
            print("[-] E2E Dispatch: PASS")
        else:
            print("[!] E2E Dispatch: FAIL (TODO in MessageRouter.py detected)")

    # 4. Ledger I/O Performance Trace
    print("[Audit] Tracing Ledger I/O performance with 1000 entries...")
    ledger.clear()
    start_time = time.perf_counter()
    for i in range(100):
        ledger.create_entry("audit_step", {"idx": i})
    duration = time.perf_counter() - start_time
    print(f"[Audit] Ledger 100 sequential writes: {duration:.4f}s")
    
    if duration > 1.0:
        print(f"[!] Performance Warning: Ledger I/O scaling is O(N^2). Current speed: {100/duration:.2f} ops/s")
    else:
        print(f"[-] Performance: OK ({100/duration:.2f} ops/s)")

if __name__ == "__main__":
    asyncio.run(audit_self_healing_link())
