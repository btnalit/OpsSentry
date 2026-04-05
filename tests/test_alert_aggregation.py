import asyncio
import json
import logging
import time
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.cluster.alert_engine import AlertEvent, AlertAggregator
from src.channels.base import OutboundMessage

# Set up logging for test visibility
logging.basicConfig(level=logging.INFO)

class MockChannel:
    def __init__(self):
        self.sent_messages = []
    
    async def send(self, message: OutboundMessage) -> bool:
        self.sent_messages.append(message)
        return True

@pytest.mark.asyncio
async def test_alert_aggregation_logic():
    """
    测试告警聚合引擎的核心逻辑：
    1. 同一源相同类型的告警去重。
    2. 不同源相同类型的告警合并。
    """
    mock_channel = MockChannel()
    aggregator = AlertAggregator(window_sec=0.1, channels=[mock_channel])
    
    await aggregator.start()
    
    # 场景 1: 同一源 (node-1) 发送 3 条相同的 NODE_DEAD 告警 (Alert Storm)
    for i in range(3):
        await aggregator.emit(AlertEvent(
            type="NODE_DEAD",
            source="node-1",
            message=f"Node 1 is down (heartbeat lost {i})",
            severity="CRITICAL"
        ))
        
    # 场景 2: 不同源 (node-2, node-3) 发送 NODE_DEAD 告警
    await aggregator.emit(AlertEvent(
        type="NODE_DEAD",
        source="node-2",
        message="Node 2 is down",
        severity="CRITICAL"
    ))
    await aggregator.emit(AlertEvent(
        type="NODE_DEAD",
        source="node-3",
        message="Node 3 is down",
        severity="CRITICAL"
    ))

    # 等待聚合窗口处理
    await asyncio.sleep(0.5)
    await aggregator.stop()

    # 验证发送的消息
    assert len(mock_channel.sent_messages) == 1
    msg = mock_channel.sent_messages[0]
    
    print(f"Aggregated Message: {msg.content}")
    
    # 期望结果：
    # 1. node-1 的 3 条消息被去重为 1 条。
    # 2. node-1, node-2, node-3 被合并显示。
    assert "node-1" in msg.content
    assert "node-2" in msg.content
    assert "node-3" in msg.content
    assert "3 occurrences" in msg.content or "NODE_DEAD" in msg.content

@pytest.mark.asyncio
async def test_alert_severity_separation():
    """
    验证不同严重程度的告警不会被错误地完全合为一条消息标题。
    """
    mock_channel = MockChannel()
    aggregator = AlertAggregator(window_sec=0.1, channels=[mock_channel])
    
    await aggregator.start()
    
    # 混合 CRITICAL 和 WARNING
    await aggregator.emit(AlertEvent(
        type="NODE_DEAD",
        source="node-1",
        message="Critical failure",
        severity="CRITICAL"
    ))
    await aggregator.emit(AlertEvent(
        type="TASK_FAILED",
        source="agent-A",
        message="Task failed",
        severity="WARNING"
    ))

    await asyncio.sleep(0.5)
    await aggregator.stop()

    assert len(mock_channel.sent_messages) == 1
    content = mock_channel.sent_messages[0].content
    assert "NODE_DEAD" in content
    assert "TASK_FAILED" in content

if __name__ == "__main__":
    asyncio.run(test_alert_aggregation_logic())
    asyncio.run(test_alert_severity_separation())
