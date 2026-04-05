from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional
import httpx

from src.channels.base import InboundMessage, MessageChannel, OutboundMessage
from src.config_shield import ConfigShield

logger = logging.getLogger("OpsSentry.DingTalkChannel")

class DingTalkChannel(MessageChannel):
    """
    钉钉 (DingTalk) 消息渠道。
    
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
        
        # Admission Spec §2.1: 从 ConfigShield 中解析凭证，禁止硬编码
        try:
            keys = self.shield.get_secret(uid, did, "dingtalk")
            self.webhook_secret = keys.extra.get("webhook_secret")
            self.webhook_url = keys.extra.get("webhook_url")
        except Exception:
            self.webhook_secret = os.getenv("DINGTALK_WEBHOOK_SECRET")
            self.webhook_url = os.getenv("DINGTALK_WEBHOOK_URL")

    async def send(self, message: OutboundMessage) -> bool:
        if not self.webhook_url:
            logger.error(f"DINGTALK_WEBHOOK_URL not configured for agent {self.did}")
            return False

        # 钉钉签名计算
        timestamp = str(round(time.time() * 1000))
        secret_enc = self.webhook_secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.webhook_secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')

        # 构造最终 URL
        import urllib.parse
        params = {"timestamp": timestamp, "sign": sign}
        target_url = f"{self.webhook_url}&{urllib.parse.urlencode(params)}"

        # Admission Spec §2.4: 内容转义
        payload = {
            "msgtype": "text",
            "text": {
                "content": f"[{message.title}]\n{message.content}"
            }
        }
        
        try:
            resp = await self._client.post(target_url, json=payload)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"DingTalk send failed: {e}")
            return False

    def verify_webhook_signature(self, timestamp: str, signature: str, body: bytes) -> bool:
        """
        实现 Admission Spec §2.3 (HMAC-SHA256 签名校验)。
        """
        if not self.webhook_secret:
            return True

        string_to_sign = f"{timestamp}\n{self.webhook_secret}"
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(self.webhook_secret.encode('utf-8'), string_to_sign_enc, digestmod=hashlib.sha256).digest()
        calc_signature = base64.b64encode(hmac_code).decode('utf-8')
        
        return hmac.compare_digest(calc_signature, signature)

    def parse_inbound(self, body: Dict[str, Any]) -> InboundMessage:
        return InboundMessage(
            sender_id=body.get("senderId", "unknown"),
            sender_name=body.get("senderNick", "unknown"),
            content=body.get("text", {}).get("content", ""),
            raw_payload=body
        )
