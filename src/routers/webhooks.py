from __future__ import annotations

import logging
import json
import time
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from pydantic import BaseModel

from src.dependencies import get_config_shield, get_ops_ledger, get_message_router
from src.config_shield import ConfigShield
from src.ops_ledger import OpsLedger
from src.message_router import MessageRouter
from src.channels.feishu import FeishuChannel
from src.channels.dingtalk import DingTalkChannel
from src.routers.sessions import manager_ws

logger = logging.getLogger("OpsSentry.Webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/feishu/{uid}/{did}")
async def feishu_webhook(
    uid: str,
    did: str,
    request: Request,
    x_lark_signature: Optional[str] = Header(None),
    x_lark_request_timestamp: Optional[str] = Header(None),
    shield: ConfigShield = Depends(get_config_shield),
    ledger: OpsLedger = Depends(get_ops_ledger),
    router_bus: MessageRouter = Depends(get_message_router)
):
    """
    飞书 Webhook 入站路由 (Phase 5 #40)。
    实现签名验证并转发至 MessageRouter 与 WebSocket。
    """
    body_bytes = await request.body()
    try:
        body_json = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 1. 初始化渠道并验签 (Admission Spec §2.3)
    channel = FeishuChannel(shield, uid, did)
    if not channel.verify_webhook_signature(x_lark_request_timestamp, x_lark_signature, body_bytes):
        logger.warning(f"Feishu webhook signature verification failed for {uid}/{did}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. 处理 URL 验证请求 (Feishu challenge)
    if body_json.get("type") == "url_verification":
        return {"challenge": body_json.get("challenge")}

    # 3. 解析消息并持久化
    inbound = channel.parse_inbound(body_json)
    
    # 记录原始事件
    ledger.create_entry(
        action="webhook_received",
        metadata={
            "channel": "feishu",
            "uid": uid,
            "did": did,
            "sender": inbound.sender_name,
            "content": inbound.content,
            "is_action": "action" in body_json
        }
    )

    # 4. 广播到 WebSocket
    external_msg = {
        "type": "external",
        "channel": "feishu",
        "sender": inbound.sender_name,
        "content": inbound.content,
        "did": did,
        "ts": int(time.time() * 1000)
    }
    await manager_ws.broadcast_global(external_msg)
    
    # 5. 分发逻辑 (普通消息 vs 交互动作)
    if "action" in body_json:
        # Phase 9 #97: 处理交互式卡片回调
        action_data = body_json["action"].get("value", {})
        logger.info(f"Received interactive action from Feishu: {action_data}")
        # 如果 MessageRouter 支持 route_action
        if hasattr(router_bus, "route_action"):
            await router_bus.route_action(
                uid=uid,
                sender_did=did,
                action_data=action_data
            )
        # 对于卡片回调，飞书通常期望返回特定的响应或空 JSON
        return {"status": "ok"}
    else:
        # 路由普通消息
        await router_bus.route_message(
            uid=uid,
            session_id=f"sess_{uid}_{did}",
            sender_did=f"external_{inbound.sender_name}",
            content=inbound.content
        )

    return {"status": "ok"}

@router.post("/dingtalk/{uid}/{did}")
async def dingtalk_webhook(
    uid: str,
    did: str,
    request: Request,
    timestamp: Optional[str] = Header(None),
    sign: Optional[str] = Header(None),
    shield: ConfigShield = Depends(get_config_shield),
    ledger: OpsLedger = Depends(get_ops_ledger),
    router_bus: MessageRouter = Depends(get_message_router)
):
    """
    钉钉 Webhook 入站路由 (Phase 5 #40)。
    """
    body_bytes = await request.body()
    try:
        body_json = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    channel = DingTalkChannel(shield, uid, did)
    if not channel.verify_webhook_signature(timestamp, sign, body_bytes):
        logger.warning(f"DingTalk webhook signature verification failed for {uid}/{did}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    inbound = channel.parse_inbound(body_json)
    
    ledger.create_entry(
        action="webhook_received",
        metadata={
            "channel": "dingtalk",
            "uid": uid,
            "did": did,
            "sender": inbound.sender_name,
            "content": inbound.content
        }
    )

    external_msg = {
        "type": "external",
        "channel": "dingtalk",
        "sender": inbound.sender_name,
        "content": inbound.content,
        "did": did
    }
    
    await manager_ws.broadcast_global(external_msg)
    
    await router_bus.route_message(
        uid=uid,
        session_id=f"sess_{uid}_{did}",
        sender_did=f"external_{inbound.sender_name}",
        content=inbound.content
    )

    return {"status": "ok"}
