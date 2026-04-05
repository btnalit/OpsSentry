import unittest
from unittest.mock import MagicMock, patch
import json
import time
from pathlib import Path
import sys
import os
import shutil
import uuid

# Add src to path
sys.path.append(os.getcwd())

from src.cluster.shipper import AuditShipper
from src.ops_ledger import OpsLedger
from src.ledger_entry import LedgerEntry

class MockRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.commands = []
    
    def xadd(self, stream, payload):
        self.commands.append(('xadd', stream, payload))
        return self

    def execute(self):
        if self.client.inject_failure:
            raise Exception("Mock Redis Connection Error")
        for cmd, stream, payload in self.commands:
            self.client.streams.setdefault(stream, []).append(payload)
        return [True] * len(self.commands)

class MockRedisClient:
    def __init__(self, url):
        self.url = url
        self.streams = {}
        self.inject_failure = False
    
    def pipeline(self):
        return MockRedisPipeline(self)
    
    def from_url(self, url, **kwargs):
        return self

def mock_redis_from_url(url, **kwargs):
    return MockRedisClient(url)

class TestAuditShipperReliability(unittest.TestCase):
    def setUp(self):
        # Use a unique sub-directory per test case to avoid WinError 32
        self.test_dir = Path(f"data/test-shipper-{uuid.uuid4().hex[:8]}")
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)
        
        self.db_path = self.test_dir / "test.db"
        self.ledger = OpsLedger(self.db_path)
        
        self.checkpoint_path = self.test_dir / "shipper.checkpoint"
        
        # Patch redis.from_url
        self.redis_patcher = patch("redis.from_url", side_effect=mock_redis_from_url)
        self.mock_redis_module = self.redis_patcher.start()
        
        self.shipper = AuditShipper(
            node_id="node-test",
            redis_url="redis://localhost:6379",
            ledger=self.ledger,
            checkpoint_path=self.checkpoint_path,
            ship_interval=0.1,
            batch_size=5
        )

    def tearDown(self):
        self.shipper.stop()
        if hasattr(self.ledger.storage, "close"):
            self.ledger.storage.close()
        self.redis_patcher.stop()
        if self.test_dir.exists():
            try:
                shutil.rmtree(self.test_dir)
            except PermissionError:
                pass # Still locked on some Windows environments

    def test_normal_shipping_and_checkpoint(self):
        """验证正常上报与断点续传"""
        # 1. 产生 10 条数据
        for i in range(10):
            self.ledger.create_entry(f"ACTION_{i}", entry_id=f"id-{i}")
        
        # 2. 运行 Shipper 扫描一次
        self.shipper._ship_batch() 
        
        # 3. 检查 Mock Redis 中的数据
        client = self.shipper._redis_client
        stream_key = f"sentry:audit:stream:node-test"
        self.assertEqual(len(client.streams.get(stream_key, [])), 5) # Batch size is 5
        
        # 4. 再次扫描
        self.shipper._ship_batch()
        self.assertEqual(len(client.streams.get(stream_key, [])), 10)
        
        # 5. 验证 Checkpoint 物理落盘
        data = json.loads(self.checkpoint_path.read_text())
        self.assertEqual(data["last_id"], "id-9")

    def test_network_partition_resilience(self):
        """验证网络分区（Redis 故障）期间的堆积与恢复"""
        # 1. 产生 5 条数据
        for i in range(5):
            self.ledger.create_entry(f"ACTION_{i}", entry_id=f"fail-id-{i}")
            
        # 2. 注入故障并尝试上报
        client = self.shipper._redis_client
        client.inject_failure = True
        
        # 这里模拟 _run_loop 中的失败逻辑
        try:
            self.shipper._ship_batch()
        except Exception:
            pass # Expected
            
        # 验证 Checkpoint 未更新
        data = json.loads(self.checkpoint_path.read_text()) if self.checkpoint_path.exists() else {"last_id": ""}
        self.assertNotEqual(data.get("last_id"), "fail-id-4")
        
        # 3. 恢复网络
        client.inject_failure = False
        self.shipper._ship_batch()
        
        # 4. 验证数据完整性
        stream_key = f"sentry:audit:stream:node-test"
        shipped = client.streams.get(stream_key, [])
        self.assertEqual(len(shipped), 5)
        self.assertEqual(json.loads(shipped[-1]["data"])["id"], "fail-id-4")

if __name__ == "__main__":
    unittest.main()
