import asyncio
import json
import logging
import time
import os
from typing import List

try:
    import redis.asyncio as async_redis
except ImportError:
    async_redis = None

from src.cluster.alert_engine import AlertEvent, AlertAggregator
from src.channels.base import OutboundMessage

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AlertStormTest")

class MockChannel:
    def __init__(self):
        self.sent_messages = []
    async def send(self, message: OutboundMessage) -> bool:
        self.sent_messages.append(message)
        return True

async def alert_emitter(aggregator: AlertAggregator, count: int, node_id: str):
    """模拟一个节点在极短时间内产生大量告警。"""
    for i in range(count):
        event = AlertEvent(
            type="TASK_FAILED",
            source=node_id,
            message=f"Storm event {i}",
            severity="WARNING" if i % 2 == 0 else "CRITICAL"
        )
        await aggregator.emit(event)

async def test_alert_storm_resilience(redis_url: str):
    """
    Phase 8 #72.4: 告警引擎极端负载压测。
    验证 Redis 缓冲区在 10,000 条告警瞬时涌入时的稳定性与聚合效率。
    """
    if not redis_url:
        logger.error("REDIS_URL is required for this stress test.")
        return

    logger.info("Starting Alert Storm Stress Test (#72.4)...")
    
    mock_channel = MockChannel()
    # 设置 5s 窗口以便观察堆积情况
    aggregator = AlertAggregator(window_sec=5.0, redis_url=redis_url, channels=[mock_channel])
    
    # 1. 清理 Redis 缓冲区
    client = async_redis.from_url(redis_url, decode_responses=True)
    await client.delete("sentry:alerts:buffer")
    
    # 2. 模拟 10 个节点，每个节点瞬发 1000 条告警 (总计 10,000 条)
    logger.info("Emitting 10,000 alerts from 10 concurrent emitters...")
    start_time = time.time()
    
    tasks = [alert_emitter(aggregator, 1000, f"node-{i}") for i in range(10)]
    await asyncio.gather(*tasks)
    
    end_time = time.time()
    logger.info(f"Emission complete. Time taken: {end_time - start_time:.2f}s")
    
    # 3. 检查 Redis 缓冲区长度
    buffer_len = await client.llen("sentry:alerts:buffer")
    logger.info(f"Redis buffer length after storm: {buffer_len}")
    assert buffer_len == 10000, f"Data loss detected! Buffer len: {buffer_len}"
    
    # 4. 启动聚合器并强制执行一次处理
    logger.info("Running aggregator batch processing...")
    await aggregator._process_batch()
    
    # 5. 验证结果
    assert len(mock_channel.sent_messages) > 0
    final_msg = mock_channel.sent_messages[0]
    
    logger.info("--- Aggregated Alert Summary ---")
    logger.info(f"Title: {final_msg.title}")
    # logger.info(f"Content:\n{final_msg.content}") # Suppressed for brevity
    logger.info("--------------------------------")
    
    # 6. 计算聚合压缩比 (Aggregation Ratio)
    # 原始 10,000 条 -> 聚合后根据 Source+Type+Severity 应为 20 条逻辑分录
    # 我们检查最终摘要中包含的行数或条目数
    lines = [line for line in final_msg.content.split("\n") if line.strip()]
    agg_count = len(lines)
    compression_ratio = (1 - (agg_count / 10000)) * 100
    logger.info(f"Aggregation Ratio: {compression_ratio:.2f}% (Aggregated {agg_count} entries from 10,000)")
    
    assert compression_ratio >= 99.0, f"Low compression ratio: {compression_ratio:.2f}%"
    
    # 预期：10,000 条消息聚合后，摘要中应提及 10 个节点的 TASK_FAILED 事件。
    # 根据当前去重逻辑 (source:type:severity)，每个节点每种严重程度保留一条。
    # node-0..9 x (WARNING, CRITICAL) = 20 条聚合分录。
    assert "TASK_FAILED" in final_msg.content
    assert "10 occurrences" in final_msg.content or "10000 events" in final_msg.title
    
    logger.info("Alert Storm Stress Test PASSED.")
    await client.close()

if __name__ == "__main__":
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    asyncio.run(test_alert_storm_resilience(url))
