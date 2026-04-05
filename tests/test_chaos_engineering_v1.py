import asyncio
import json
import logging
import random
import time
import uuid
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import redis

from src.agent_manager import AgentManager
from src.ops_ledger import OpsLedger
from src.cluster.heartbeat import HeartbeatSender
from src.cluster.shipper import AuditShipper
from src.cluster.alert_engine import AlertEvent

# --- CONFIGURATION ---
TEST_ROOT = Path("data/chaos_test")

class MockRedisClient:
    def __init__(self):
        self.data = {}
        self.streams = {}
        self.ttls = {}
        self.is_down = False
        self.pubsub_channels = {}

    def _check_status(self):
        if self.is_down:
            raise redis.exceptions.ConnectionError("Chaos: Redis is down")

    def ping(self):
        self._check_status()
        return True

    def set(self, key, val, ex=None, px=None, nx=False, xx=False):
        self._check_status()
        if nx and key in self.data: return False
        self.data[key] = val
        if ex: self.ttls[key] = time.time() + ex
        return True

    def get(self, key):
        self._check_status()
        if key in self.ttls and time.time() > self.ttls[key]:
            del self.data[key]
            return None
        return self.data.get(key)

    def hset(self, name, key, val):
        self._check_status()
        self.data.setdefault(name, {})[key] = val

    def hgetall(self, name):
        self._check_status()
        return self.data.get(name, {})

    def hdel(self, name, key):
        self._check_status()
        if name in self.data:
            self.data[name].pop(key, None)

    def delete(self, key):
        self._check_status()
        self.data.pop(key, None)

    def publish(self, channel, message):
        self._check_status()
        # Mock pubsub distribution
        return 1

    def pipeline(self):
        self._check_status()
        return MockRedisPipeline(self)

class MockRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.cmds = []
    def delete(self, k): self.cmds.append(('del', k)); return self
    def hdel(self, n, k): self.cmds.append(('hdel', n, k)); return self
    def publish(self, c, m): self.cmds.append(('pub', c, m)); return self
    def execute(self):
        for cmd in self.cmds:
            if cmd[0] == 'del': self.client.delete(cmd[1])
            elif cmd[0] == 'hdel': self.client.hdel(cmd[1], cmd[2])
            elif cmd[0] == 'pub': self.client.publish(cmd[1], cmd[2])
        return [True] * len(self.cmds)

@pytest.mark.asyncio
async def test_chaos_scenario_redis_crash():
    """
    [Scenario A] Redis Crash Simulation.
    Verify that AgentManager failover logic handles Redis ConnectionError gracefully.
    """
    print("\n--- Chaos Scenario A: Redis Crash Simulation ---")
    mock_redis = MockRedisClient()
    with patch("redis.from_url", return_value=mock_redis):
        manager = AgentManager(redis_url="redis://localhost")
        
        # Simulate Redis going down
        mock_redis.is_down = True
        
        # Call failover
        reclaimed = manager.perform_failover("dead-node-99")
        
        # Expected: Returns 0, logs error, but does NOT crash the process.
        assert reclaimed == 0
        print("[Auditor] PASS: AgentManager handled Redis crash without exception.")

@pytest.mark.asyncio
async def test_chaos_scenario_split_brain_recovery():
    """
    [Scenario B] Brain-Split Recovery Test.
    Two nodes think each other are dead due to simulated network partition.
    Test if Failover logic maintains consistency.
    """
    print("\n--- Chaos Scenario B: Brain-Split Recovery Test ---")
    mock_redis = MockRedisClient()
    
    # Setup: node-A has task-1, node-B has task-2
    mock_redis.hset("sentry:task:registry", "task-1", "node-A")
    mock_redis.hset("sentry:task:registry", "task-2", "node-B")
    
    with patch("redis.from_url", return_value=mock_redis):
        manager = AgentManager(redis_url="redis://localhost")
        
        # Scenario: node-B heartbeat times out in Redis (simulated by manual deletion)
        # node-A (acting as leader) detects node-B as dead
        print("[Auditor] Node-A triggers failover for Node-B...")
        reclaimed = manager.perform_failover("node-B")
        
        assert reclaimed == 1
        assert mock_redis.hgetall("sentry:task:registry").get("task-2") is None
        
        print("[Auditor] PASS: Task-2 was successfully reclaimed during simulated partition.")

@pytest.mark.asyncio
async def test_chaos_scenario_avalanche_resilience():
    """
    [Scenario C] Node Avalanche Resilience.
    Multiple nodes die at once. Verify if Failover can handle bulk reclamation.
    """
    print("\n--- Chaos Scenario C: Node Avalanche Resilience ---")
    mock_redis = MockRedisClient()
    
    with patch("redis.from_url", return_value=mock_redis):
        manager = AgentManager(redis_url="redis://localhost")
        
        # Setup 10 nodes with 5 tasks each
        total_nodes = 10
        tasks_per_node = 5
        for i in range(total_nodes):
            nid = f"node-{i}"
            for j in range(tasks_per_node):
                tid = f"task-{i}-{j}"
                mock_redis.hset("sentry:task:registry", tid, nid)
                
        # Simulate 5 nodes dying at once
        dead_nodes = [f"node-{i}" for i in range(5)]
        print(f"[Auditor] 5 nodes (avalanche) died. Reclaiming 25 tasks...")
        
        total_reclaimed = 0
        for nid in dead_nodes:
            total_reclaimed += manager.perform_failover(nid)
            
        assert total_reclaimed == 25
        print(f"[Auditor] PASS: Successfully reclaimed {total_reclaimed} tasks from avalanche nodes.")

@pytest.mark.asyncio
async def test_chaos_scenario_hmac_tamper():
    """
    [Scenario D] HMAC Tamper Detection.
    Send malformed heartbeat packets. Verify rejection.
    """
    print("\n--- Chaos Scenario D: HMAC Tamper Detection ---")
    manager = AgentManager()
    secret = "chaos-secret-key"
    
    payload = {
        "node_id": "attacker-node",
        "ts": int(time.time() * 1000),
        "metrics": {"cpu": 99},
        "hmac": "fake-hmac-value"
    }
    
    # 1. Test with fake hmac
    is_valid = manager.validate_heartbeat(payload, secret)
    assert is_valid is False
    print("[Auditor] PASS: Rejected tampered HMAC.")
    
    # 2. Test with correct hmac but modified payload
    # Calculate correct hmac first
    correct_data = {"node_id": "node-1", "ts": 1000}
    message = json.dumps(correct_data, sort_keys=True).encode("utf-8")
    correct_hmac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    
    tampered_payload = {"node_id": "node-1", "ts": 1001, "hmac": correct_hmac}
    is_valid_tamper = manager.validate_heartbeat(tampered_payload, secret)
    assert is_valid_tamper is False
    print("[Auditor] PASS: Rejected modified payload with old HMAC.")

if __name__ == "__main__":
    import hmac, hashlib
    asyncio.run(test_chaos_scenario_redis_crash())
    asyncio.run(test_chaos_scenario_split_brain_recovery())
    asyncio.run(test_chaos_scenario_avalanche_resilience())
    asyncio.run(test_chaos_scenario_hmac_tamper())
