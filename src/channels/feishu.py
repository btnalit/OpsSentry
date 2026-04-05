from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from src.channels.base import InboundMessage, MessageChannel, OutboundMessage
from src.config_shield import ConfigShield

logger = logging.getLogger("OpsSentry.FeishuChannel")

class FeishuChannel(MessageChannel):
    """
    飞书 (Feishu/Lark) 消息渠道。
    
    实现准入测试规范 (Admission Spec v34):
    - 2.1 凭证读取 (ConfigShield / os.environ)
    - 2.3 签名校验 (HMAC-SHA256)
    - 2.4 内容转义
    """

    def __init__(self, shield: ConfigShield, uid: str, did: str) -> None:
        self.shield = shield
        self.uid = uid
        self.did = did
        self._client = httpx.AsyncClient(timeout=10.0)
        
        # Admission Spec §2.1: 通过 ConfigShield 动态解析凭证，禁止硬编码
        try:
            keys = self.shield.get_secret(uid, did, "feishu")
            self.app_id = keys.api_key
            self.app_secret = keys.extra.get("app_secret")
            self.webhook_secret = keys.extra.get("webhook_secret")
            self.webhook_url = keys.extra.get("webhook_url")
        except Exception as e:
            logger.warning(f"Failed to get Feishu secret via ConfigShield: {e}. Falling back to env.")
            self.app_id = os.getenv("FEISHU_APP_ID")
            self.app_secret = os.getenv("FEISHU_APP_SECRET")
            self.webhook_secret = os.getenv("FEISHU_WEBHOOK_SECRET")
            self.webhook_url = os.getenv("FEISHU_WEBHOOK_URL")

    async def send(self, message: OutboundMessage) -> bool:
        if not self.webhook_url:
            logger.error(f"FEISHU_WEBHOOK_URL not configured for agent {self.did}")
            return False

        # Admission Spec §2.4: 结构化消息，防止非法字符破坏 JSON
        if message.msg_type == "interactive":
            # 构造飞书卡片消息 (Interactive Card)
            payload = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True
                    },
                    "header": {
                        "template": "blue",
                        "title": {
                            "tag": "plain_text",
                            "content": message.title
                        }
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": message.content
                            }
                        }
                    ]
                }
            }
            
            # 如果有 extra 包含 actions (例如按钮)
            if message.extra and "actions" in message.extra:
                action_element = {
                    "tag": "action",
                    "actions": []
                }
                for act in message.extra["actions"]:
                    action_element["actions"].append({
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": act.get("text", "Button")
                        },
                        "type": act.get("type", "default"),
                        "value": act.get("value", {})
                    })
                payload["card"]["elements"].append(action_element)
        else:
            # 默认文本消息
            payload = {
                "msg_type": "text",
                "content": {
                    "text": f"[{message.title}]\n{message.content}"
                }
            }
        
        try:
            resp = await self._client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Feishu send failed: {e}")
            return False

    def verify_webhook_signature(self, timestamp: str, signature: str, body: bytes) -> bool:
        """
        实现 Admission Spec §2.3 (HMAC-SHA256 签名校验)。
        """
        if not self.webhook_secret:
            return True # 开发模式

        string_to_sign = f"{timestamp}\n{self.webhook_secret}"
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), body, hashlib.sha256).digest()
        calc_signature = base64.b64encode(hmac_code).decode("utf-8")
        
        return hmac.compare_digest(calc_signature, signature)

    def parse_inbound(self, body: Dict[str, Any]) -> InboundMessage:
        # 1. 处理卡片交互回调 (Interactive Card Callback)
        if "action" in body:
            action = body["action"]
            value = action.get("value", {})
            action_type = value.get("action", "unknown_action")
            
            return InboundMessage(
                sender_id=body.get("open_id", "unknown"),
                sender_name=body.get("user_id", "unknown"), # 卡片回调通常只有 ID
                content=f"/action {action_type} {json.dumps(value)}",
                raw_payload=body
            )

        # 2. 处理普通消息事件 (Message Event)
        event = body.get("event", {})
        sender = event.get("sender", {})
        message = event.get("message", {})
        
        return InboundMessage(
            sender_id=sender.get("sender_id", {}).get("open_id", "unknown"),
            sender_name=sender.get("sender_id", {}).get("name", "unknown"),
            content=message.get("content", ""),
            raw_payload=body
        )
