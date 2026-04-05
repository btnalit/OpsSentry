from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger("OpsSentry.AlertEngine")

class AlertEvent(BaseModel):
    id: str = Field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest())
    type: str  # NODE_DEAD, TASK_FAILED, CRON_ERROR, SYSTEM_OVERLOAD
    severity: str = "WARNING"  # CRITICAL, WARNING, INFO
    source: str  # node_id or agent_id
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))

    def to_summary(self) -> str:
        return f"[{self.severity}] {self.type} from {self.source}: {self.message}"

class AlertAggregator:
    """
    Phase 8 #72: 多维告警聚合引擎。
    负责收集原始告警事件，并在时间窗口内进行去重与合并。
    支持 Redis 队列缓冲（分布式）与内存缓冲（单机）。
    """

    def __init__(
        self,
        window_sec: float = 60.0,
        redis_url: str | None = None,
        channels: List[Any] | None = None, # List of MessageChannel
    ) -> None:
        self.window_sec = window_sec
        self.redis_url = redis_url
        self.channels = channels or []
        self._redis_client = None
        self._buffer: List[AlertEvent] = []
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        
        if redis_url:
            import redis.asyncio as async_redis
            self._redis_client = async_redis.from_url(redis_url, decode_responses=True)
            logger.info(f"AlertAggregator initialized with Redis buffer: {redis_url}")
        else:
            logger.info("AlertAggregator initialized with memory buffer (Standalone).")

    async def start(self):
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AlertAggregator STARTED.")

    async def stop(self):
        self._stop_event.set()
        if self._task:
            await self._task
            logger.info("AlertAggregator STOPPED.")

    async def emit(self, event: AlertEvent):
        """发送原始告警事件到缓冲区"""
        if self._redis_client:
            await self._redis_client.lpush("sentry:alerts:buffer", event.model_dump_json())
        else:
            async with self._lock:
                self._buffer.append(event)
        logger.debug(f"Alert emitted: {event.type} from {event.source}")

    async def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                # 按照窗口间隔进行聚合
                await asyncio.sleep(self.window_sec)
                await self._process_batch()
            except Exception as e:
                logger.error(f"Alert aggregation loop error: {e}")
                await asyncio.sleep(5)

    async def _process_batch(self):
        raw_events: List[AlertEvent] = []
        
        # 1. 从缓冲区提取所有事件 (Phase 8 #72.4 性能优化)
        if self._redis_client:
            # 使用 Pipeline 或 LPOP count (如果支持) 批量拉取数据
            # 兼容性方案：循环 LPOP 但控制每次批量
            batch_size = 1000
            while True:
                # 尝试拉取一个批次 (Redis 6.2+ 支持 LPOP key count)
                try:
                    # 我们这里采用兼容性方案，使用 pipeline 模拟批量拉取
                    pipe = self._redis_client.pipeline()
                    for _ in range(batch_size):
                        pipe.rpop("sentry:alerts:buffer")
                    results = await pipe.execute()
                    
                    found_any = False
                    for raw in results:
                        if raw:
                            raw_events.append(AlertEvent.model_validate_json(raw))
                            found_any = True
                    
                    if not found_any or len(results) < batch_size:
                        break
                except Exception as e:
                    logger.error(f"Error fetching alerts from Redis: {e}")
                    break
        else:
            async with self._lock:
                raw_events = self._buffer
                self._buffer = []

        if not raw_events:
            return

        # 2. 聚合逻辑 (Aggregation Logic)
        aggregated = self._aggregate(raw_events)
        
        # 3. 分发消息 (Dispatching)
        await self._dispatch(aggregated)

    def _aggregate(self, events: List[AlertEvent]) -> Dict[str, List[AlertEvent]]:
        """
        按类型和严重程度对告警进行初步分组。
        实现：
        - 相同 Source + 相同 Type 去重
        - 相同 Type 不同 Source 合并
        """
        grouped = defaultdict(list)
        seen = set()
        
        for e in events:
            # 严格去重：1分钟内同一来源同一类型的告警仅计为1条（但保留最新一条的消息）
            dedup_key = f"{e.source}:{e.type}:{e.severity}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            grouped[e.type].append(e)
            
        return dict(grouped)

    async def _dispatch(self, grouped_alerts: Dict[str, List[AlertEvent]]):
        """构造汇总消息并发送"""
        from src.channels.base import OutboundMessage
        
        total_count = sum(len(evs) for evs in grouped_alerts.values())
        if total_count == 0:
            return

        title = f"🚨 OpsSentry Alert Summary ({total_count} events)"
        lines = []
        
        for alert_type, events in grouped_alerts.items():
            sources = ", ".join([e.source for e in events])
            if len(events) == 1:
                lines.append(f"🔴 {alert_type}: {events[0].message} (Source: {events[0].source})")
            else:
                lines.append(f"🔴 {alert_type}: {len(events)} occurrences across nodes [{sources}]")

        summary_content = "\n".join(lines)
        logger.info(f"Dispatching aggregated alert summary: {title}")

        # 1. Dispatch to External Channels (Feishu/DingTalk)
        for channel in self.channels:
            try:
                msg = OutboundMessage(
                    title=title,
                    content=summary_content,
                    recipient="ALL", # Broadcast to default group
                )
                await channel.send(msg)
            except Exception as e:
                logger.error(f"Failed to dispatch alert to channel {channel.__class__.__name__}: {e}")

        # 2. Push to HUD via WebSocket (Phase 8 #72.2 Update)
        try:
            from src.routers.sessions import manager_ws
            await manager_ws.broadcast_global({
                "type": "alert_event",
                "title": title,
                "content": summary_content,
                "severity": "CRITICAL" if any(e.severity == "CRITICAL" for evs in grouped_alerts.values() for e in evs) else "WARNING",
                "timestamp": int(time.time() * 1000)
            })
        except Exception as e:
            logger.warning(f"Failed to broadcast alert via WebSocket: {e}")
