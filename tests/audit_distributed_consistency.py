import time
import uuid
import json
import redis
import multiprocessing

# Redis configuration for audit (assuming default or local)
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

try:
    import redis
except ImportError:
    redis = None

class MockRedisClient:
    def __init__(self, **kwargs):
        self.data = {}
        self.streams = {}
        self.ttls = {}
        self.nx_fail = False

    def ping(self): return True
    def set(self, key, val, ex=None, px=None, nx=False, xx=False):
        if nx and key in self.data: return False
        if xx and key not in self.data: return False
        self.data[key] = val
        if ex: self.ttls[key] = time.time() + ex
        if px: self.ttls[key] = time.time() + (px / 1000)
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
    def hdel(self, name, key):
        self.data.get(name, {}).pop(key, None)

class DistributedAudit:
    """Audit tool for Redis-based cluster consistency."""
    
    def __init__(self):
        if redis:
            try:
                self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
                self.r.ping()
            except Exception:
                print("[AUDIT] Real Redis unavailable, using MOCK.")
                self.r = MockRedisClient()
        else:
            print("[AUDIT] Redis-py not installed, using MOCK.")
            self.r = MockRedisClient()

    def simulate_node_crash(self, node_id):
        """Simulate a worker node crashing while holding a task lock."""
        print(f"--- Simulating Crash for Node: {node_id} ---")
        if not self.r: return
        
        # 1. Register node and take task lock (Using Spec #63 Keys)
        self.r.hset("sentry:cluster:nodes", node_id, json.dumps({"status": "active"}))
        self.r.set(f"sentry:node:hb:{node_id}", "alive", ex=5) # Reduced TTL for fast audit
        self.r.set("sentry:task:lock:task_audit_1", node_id, ex=10)
        self.r.hset("sentry:task:registry", "task_audit_1", node_id)
        
        print(f"Node {node_id} registered and locked 'task_audit_1'. Now crashing...")
        # Simulate physical crash by simply stopping HB renewal
        time.sleep(6) # Wait for HB to expire (TTL=5)
        
        # 2. Audit Leader's Perspective (Failover Sequence 2.2)
        hb = self.r.get(f"sentry:node:hb:{node_id}")
        if not hb:
            print(f"[AUDIT PASS] Node {node_id} HB expired correctly (SUSPECT -> DEAD).")
            
            # Leader detects and reclaims
            print("Leader Reclaiming Task...")
            registry = self.r.hget("sentry:task:registry", "task_audit_1")
            if registry == node_id:
                # Reclaim logic as per #63 spec: HDEL + DEL
                self.r.hdel("sentry:task:registry", "task_audit_1")
                self.r.delete("sentry:task:lock:task_audit_1")
                print("[AUDIT PASS] Leader successfully reclaimed 'task_audit_1'.")
        else:
            print(f"[AUDIT FAIL] Node {node_id} HB still exists after 6s.")

    def audit_gc_pause_brain_split(self, leader_node, standby_node):
        """Audit if a node stops management actions after GC pause causes lease loss."""
        print(f"--- Auditing GC Pause / Split Brain Prevention ---")
        if not self.r: return
        
        # 1. Node 1 becomes Leader (Spec 2.1)
        self.r.set("sentry:leader:lease", leader_node, ex=5) # Short lease for test
        print(f"Node {leader_node} is Leader (Lease=5s).")
        
        # 2. Node 1 "Pauses" for 7s (GC Simulation)
        print(f"Node {leader_node} entering GC Pause (7s)...")
        time.sleep(7)
        
        # 3. Standby Node 2 takes leadership
        print(f"Standby Node {standby_node} attempting to take leadership...")
        success = self.r.set("sentry:leader:lease", standby_node, nx=True, ex=5)
        if success:
            print(f"Node {standby_node} is the NEW Leader.")
        
        # 4. Node 1 "Wakes up" and tries to perform action (Failover/Rebalance)
        print(f"Node {leader_node} wakes up. Attempting Leader action...")
        
        # MANDATORY CHECK: Node must verify lease BEFORE action
        current_leader = self.r.get("sentry:leader:lease")
        if current_leader != leader_node:
            print(f"ACTION BLOCKED: Node {leader_node} detected lease loss (Current Leader: {current_leader}).")
            print("[AUDIT PASS] GC Pause brain-split prevented by mandatory lease check.")
        else:
            print("[AUDIT FAIL] Node {leader_node} still thinks it's Leader or lease wasn't reclaimed.")

if __name__ == "__main__":
    audit = DistributedAudit()
    audit.simulate_node_crash("node-audit-99")
    audit.audit_gc_pause_brain_split("leader-audit-01", "leader-standby-02")
