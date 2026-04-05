from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
from pydantic import BaseModel

from src.ops_ledger import OpsLedger
from src.agent_manager import AgentManager

logger = logging.getLogger("OpsSentry.MessageRouter")

class MessageRouter:
    """
    消息路由总线。
    负责处理 @mention 逻辑及跨 Agent 的运维事件链分发。
    """

    def __init__(self, manager: AgentManager, ledger: OpsLedger) -> None:
        self.manager = manager
        self.ledger = ledger

    async def route_message(self, uid: str, session_id: str, sender_did: str, content: str) -> None:
        """
        处理单条消息，识别 @mention 并路由至指定运维 Agent。
        """
        # TODO: 接入 LLM 语义识别或正则匹配 @mention
        mentions = self._extract_mentions(content)
        
        # 记录运维事件链 (OpsLedger §3.5)
        self.ledger.create_entry(
            action="message_routed",
            metadata={
                "session_id": session_id,
                "sender_did": sender_did,
                "mentions": mentions,
                "content": content
            }
        )
        
        # 实际分发逻辑 (异步调用指定 AgentVM 进行推理并回复)
        for target_did in mentions:
            logger.info(f"Routing message to {target_did} from {sender_did}")
            # Phase 5 #40: 调用 AgentVM 推理回路
            from src.agent_vm import create_agent_vm
            from src.session_manager import SessionManager
            from src.dependencies import get_session_manager
            
            # TODO: 确定 session_id 映射策略
            vm = create_agent_vm(uid, target_did)
            
            # 获取会话历史
            session_mgr: SessionManager = get_session_manager()
            # 临时使用 session_id 或者根据 uid/did 创建
            session = session_mgr.get_or_create_session(uid, target_did, session_id)
            history = session_mgr.load_history(session.id)
            
            # 注入用户指令
            user_msg = {"role": "user", "content": content}
            history.append(user_msg)
            session_mgr.append_history(session.id, user_msg)
            
            # 非阻塞执行推理 (由于这是 Webhook 路由，不一定需要实时回传流，
            # 但为了触发自愈工具，我们需要运行 vm.chat，并向 UI 广播)
            from src.routers.sessions import manager_ws
            
            async def run_inference():
                async for chunk in vm.chat(history):
                    # 1. 向 UI 广播实时日志 (Phase 5 #42 HUD 联动)
                    mapped_chunk = chunk.copy()
                    # 对齐前端渲染协议 (Phase 4)
                    if chunk["type"] == "content":
                        mapped_chunk["type"] = "thought"
                    elif chunk["type"] == "tool_call":
                        mapped_chunk["type"] = "call"
                    elif chunk["type"] == "tool_result":
                        mapped_chunk["type"] = "observation"
                    
                    # 广播给全局或指定会话
                    await manager_ws.broadcast_global({
                        "type": "agent_stream",
                        "did": target_did,
                        "session_id": session.id,
                        "payload": mapped_chunk
                    })
                    
                    # 2. 如果是最终消息，存入历史
                    if chunk["type"] == "message":
                        session_mgr.append_history(session.id, chunk["message"])
                    
                    # 3. 记录审计流水 (OpsLedger)
                    self.ledger.create_entry("agent_action", {
                        "did": target_did,
                        "type": mapped_chunk["type"],
                        "payload": mapped_chunk
                    })
            
            # 在后台运行推理
            import asyncio
            asyncio.create_task(run_inference())

    async def route_action(self, uid: str, sender_did: str, action_data: Dict[str, Any]) -> None:
        """
        处理交互式卡片回调动作 (Phase 9 #97)。
        """
        action_name = action_data.get("action", "unknown")
        logger.info(f"Routing interactive action '{action_name}' from {sender_did}")
        
        # 1. 记录审计
        self.ledger.create_entry(
            action="interactive_action",
            metadata={
                "uid": uid,
                "sender_did": sender_did,
                "action_name": action_name,
                "data": action_data
            }
        )
        
        # 2. 广播到 WebSocket UI (Phase 9 #99 HUD 联动)
        from src.routers.sessions import manager_ws
        import time
        await manager_ws.broadcast_global({
            "type": "system_event",
            "event": "interactive_action",
            "payload": {
                "action": action_name,
                "data": action_data,
                "did": sender_did,
                "ts": int(time.time() * 1000)
            }
        })

        # 3. 如果是特定动作 (例如 'approve'), 可以触发业务逻辑
        # TODO: 集成任务审批流
        if action_name == "approve":
            logger.info(f"Task approved via interactive card: {action_data.get('task_id')}")
            # 更新任务状态 (逻辑待补充)

    def _extract_mentions(self, content: str) -> List[str]:
        # 正则匹配 @DID-XXXX-XXXX
        import re
        pattern = r"@DID-[0-9A-F]{8}-[0-9A-F]{6}"
        return re.findall(pattern, content)
