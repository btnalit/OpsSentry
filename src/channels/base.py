from __future__ import annotations

import abc
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger("OpsSentry.Channel")

class OutboundMessage(BaseModel):
    title: str
    content: str
    recipient: str  # Channel-specific ID (e.g. chat_id)
    msg_type: str = "text" # text, interactive, etc.
    extra: Optional[Dict[str, Any]] = None # Card actions, buttons, etc.

class InboundMessage(BaseModel):
    sender_id: str
    sender_name: str
    content: str
    raw_payload: Dict[str, Any]

class MessageChannel(abc.ABC):
    """
    消息渠道基类。
    所有渠道（Feishu, DingTalk 等）必须实现 send 和 Webhook 校验。
    """

    @abc.abstractmethod
    async def send(self, message: OutboundMessage) -> bool:
        """发送消息到外部渠道"""
        pass

    @abc.abstractmethod
    def verify_webhook_signature(self, timestamp: str, signature: str, body: bytes) -> bool:
        """校验 Webhook 入站请求签名 (Admission Spec §2.3)"""
        pass

    @abc.abstractmethod
    def parse_inbound(self, body: Dict[str, Any]) -> InboundMessage:
        """解析第三方平台的 Webhook Payload 为统一格式"""
        pass
