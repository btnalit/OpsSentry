import multiprocessing
import time
import os
import sys
import json
import uuid
import random
from pathlib import Path
import redis
from unittest.mock import patch

# --- CONFIGURATION ---
NUM_NODES = 3
TEST_ROOT = Path("data/cluster_integration_test")

# Ensure src is in path
sys.path.append(os.getcwd())

from src.ops_ledger import OpsLedger
from src.agent_manager import AgentManager
from src.cluster.shipper import AuditShipper

# Mocking the redis client for integration test
class MockRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.commands = []
    def xadd(self, stream, payload):
        self.commands.append(('xadd', stream, payload))
        return self
    def delete(self, key):
        self.commands.append(('delete', key))
        return self
    def hdel(self, name, key):
        self.commands.append(('hdel', name, key))
        return self
    def publish(self, channel, message):
        self.commands.append(('publish', channel, message))
        return self
    def execute(self):
        results = []
        for cmd in self.commands:
            action = cmd[0]
            if action == 'xadd':
                stream, payload = cmd[1], cmd[2]
                self.client.streams.setdefault(stream, []).append(payload)
                results.append(True)
            elif action == 'delete':
                self.client.delete(cmd[1])
                results.append(True)
            elif action == 'hdel':
                self.client.hdel(cmd[1], cmd[2])
                results.append(True)
            elif action == 'publish':
                results.append(1) # Subscriptions count
        return results

class MockRedisClient:
    def __init__(self, **kwargs):
        self.data = {}
        self.streams = {}
        self.ttls = {}
    def ping(self): return True
    def pipeline(self): return MockRedisPipeline(self)
    def from_url(self, *args, **kwargs): return self
    def set(self, key, val, ex=None, px=None, nx=False, xx=False):
        if nx and key in self.data: return False
        if xx and key not in self.data: return False
        self.data[key] = val
        if ex: self.ttls[key] = time.time() + ex
        if px: self.ttls[key] = time.time() + (px / 1000.0)
        return True
    def get(self, key):
        if key in self.ttls and time.time() > self.ttls[key]:
            del self.data[key]
            del self.ttls[key]
            return None
        return self.data.get(key)
    def delete(self, key):
        self.data.pop(key, None)
        self.ttls.pop(key, None)
    def hset(self, name, key, val):
        self.data.setdefault(name, {})[key] = val
    def hget(self, name, key):
        return self.data.get(name, {}).get(key)
    def hgetall(self, name):
        return self.data.get(name, {})
    def hdel(self, name, key):
        if name in self.data:
            self.data[name].pop(key, None)
    def publish(self, channel, message):
        return 0
    def keys(self, pattern):
        import fnmatch
        return [k for k in self.data.keys() if fnmatch.fnmatch(k, pattern.replace("*", "*"))]

SHARED_MOCK_REDIS = MockRedisClient()

class SimulatedNode(multiprocessing.Process):
    """A simulated cluster node running an AgentManager and AuditShipper."""
    
    def __init__(self, node_id: str, redis_url: str):
        super().__init__()
        self.node_id = node_id
        self.redis_url = redis_url
        self.stop_event = multiprocessing.Event()
        self.node_dir = TEST_ROOT / node_id
        self.db_path = self.node_dir / "ledger.db"

    def run(self):
        print(f"[Node {self.node_id}] Starting up...")
        self.node_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Initialize Components
        ledger = OpsLedger(self.db_path)
        
        # Patch redis in the process
        with patch("redis.from_url", return_value=SHARED_MOCK_REDIS):
            manager = AgentManager(node_id=self.node_id, redis_url=self.redis_url)
            shipper = AuditShipper(
                node_id=self.node_id,
                redis_url=self.redis_url,
                ledger=ledger,
                checkpoint_path=self.node_dir / "shipper.checkpoint"
            )
            
            # 2. Simulation Loop
            try:
                while not self.stop_event.is_set():
                    # Perform mock heartbeat manually (simulating AgentManager loop)
                    # Use the manager's internal method to update metrics in Redis
                    metrics = {"cpu": random.uniform(10, 50), "mem": random.uniform(20, 60), "tasks": random.randint(0, 5)}
                    hb_data = {"ts": int(time.time() * 1000), "metrics": metrics}
                    SHARED_MOCK_REDIS.set(f"sentry:node:hb:{self.node_id}", json.dumps(hb_data), ex=30)
                    SHARED_MOCK_REDIS.hset("sentry:cluster:nodes", self.node_id, json.dumps({"status": "ACTIVE"}))
                    
                    # Ship any new logs
                    shipper._ship_batch()
                    
                    time.sleep(1)
            except Exception as e:
                print(f"[Node {self.node_id}] Fatal Error: {e}")
            finally:
                print(f"[Node {self.node_id}] Shutting down.")
                # Manual unregister for mock
                SHARED_MOCK_REDIS.hdel("sentry:cluster:nodes", self.node_id)
                SHARED_MOCK_REDIS.delete(f"sentry:node:hb:{self.node_id}")

def run_integration_test():
    print(f"--- OpsSentry 3-Node Cluster Integration Test (#65) ---")
    
    if TEST_ROOT.exists():
        import shutil
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True)

    from threading import Thread, Event
    from src.cluster.heartbeat import HeartbeatSender
    from src.routers.cluster import get_cluster_status
    from unittest.mock import MagicMock

    # 1. Start Nodes with real HeartbeatSender (but mocked Redis)
    nodes = []
    senders = []
    for i in range(NUM_NODES):
        node_id = f"node-{i}"
        with patch("redis.from_url", return_value=SHARED_MOCK_REDIS):
            sender = HeartbeatSender(node_id=node_id, redis_url="mock://", secret="test-secret")
            senders.append(sender)
            sender.start()
            print(f"[Auditor] Node {node_id} heartbeat started.")

    time.sleep(2) # Wait for first heartbeats
    
    # 2. Audit Cluster State via the real Status Router logic
    print("\n[Auditor] Verifying cluster status via API logic...")
    mock_manager = MagicMock()
    mock_manager._redis_client = SHARED_MOCK_REDIS
    
    status = asyncio.run(get_cluster_status(manager=mock_manager))
    print(f"[Auditor] API reported nodes: {len(status['nodes'])}")
    for n in status['nodes']:
        print(f"  - {n['id']}: {n['status']} (Last seen: {n['last_seen']})")
        assert n['status'] == "ACTIVE"

    # 3. Simulate Failure (Stop node-0 heartbeat)
    target_node = "node-0"
    print(f"\n[Auditor] Simulating STOP for {target_node}...")
    for s in senders:
        if s.node_id == target_node:
            s.stop()
            break
    
    # Manually warp time in Mock Redis to test state machine transitions
    print(f"[Auditor] Warping time +20s (expecting SUSPECT)...")
    # Instead of waiting, we modify the TS in Redis
    hb_key = f"sentry:node:hb:{target_node}"
    raw_hb = SHARED_MOCK_REDIS.get(hb_key)
    hb_data = json.loads(raw_hb)
    hb_data["ts"] -= 20000 # Backdate by 20s
    SHARED_MOCK_REDIS.set(hb_key, json.dumps(hb_data))
    
    status_suspect = asyncio.run(get_cluster_status(manager=mock_manager))
    for n in status_suspect['nodes']:
        if n['id'] == target_node:
            print(f"  - {n['id']} status: {n['status']} [EXPECTED: SUSPECT]")
            assert n['status'] == "SUSPECT"

    print(f"[Auditor] Warping time +40s total (expecting DEAD)...")
    hb_data["ts"] -= 20000 # Backdate another 20s (total 40s)
    SHARED_MOCK_REDIS.set(hb_key, json.dumps(hb_data))
    
    status_dead = asyncio.run(get_cluster_status(manager=mock_manager))
    for n in status_dead['nodes']:
        if n['id'] == target_node:
            print(f"  - {n['id']} status: {n['status']} [EXPECTED: DEAD]")
            assert n['status'] == "DEAD"

    # 4. Test Failover logic
    print(f"\n[Auditor] Testing Failover for {target_node}...")
    # Setup a mock task registered to this node
    SHARED_MOCK_REDIS.hset("sentry:task:registry", "task-101", target_node)
    
    # Run failover via AgentManager
    from src.agent_manager import AgentManager
    with patch("redis.from_url", return_value=SHARED_MOCK_REDIS):
        manager = AgentManager(redis_url="mock://")
        reclaimed = manager.perform_failover(target_node)
        print(f"[Auditor] Reclaimed tasks: {reclaimed}")
        assert reclaimed == 1
        
        # Verify task is cleared from registry
        registry = SHARED_MOCK_REDIS.hgetall("sentry:task:registry")
        assert "task-101" not in registry

    # 5. Cleanup
    for s in senders:
        s.stop()
        
    print("\n[AUDIT PASS] #65 Distributed Cluster Integration Logic Verified.")

if __name__ == "__main__":
    import asyncio
    run_integration_test()
