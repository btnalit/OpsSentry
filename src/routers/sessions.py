from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from src.agent_vm import create_agent_vm
from src.dependencies import get_session_manager, get_agent_manager
from src.session_manager import SessionManager

logger = logging.getLogger("OpsSentry.Sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"])

class ConnectionManager:
    """
    WebSocket 连接管理器。
    负责维护活动的 WebSocket 连接，支持向特定会话广播 EXTERNAL 消息。
    """
    def __init__(self):
        # 存储格式: {session_id: [websocket1, websocket2, ...]}
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self._redis_sub_task: Optional[asyncio.Task] = None

    def start_redis_subscriber(self, redis_url: str):
        """
        启动 Redis 订阅者，监听集群广播消息并推送至 WebSocket。
        """
        if self._redis_sub_task and not self._redis_sub_task.done():
            return

        self._redis_sub_task = asyncio.create_task(self._redis_subscriber_loop(redis_url))
        logger.info("Redis Cluster Event Subscriber STARTED")

    async def _redis_subscriber_loop(self, redis_url: str):
        import redis.asyncio as async_redis
        
        while True:
            try:
                client = async_redis.from_url(redis_url, decode_responses=True)
                pubsub = client.pubsub()
                await pubsub.subscribe("sentry:msg:broadcast")
                
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            # 将集群事件包装为系统通知广播给前端
                            await self.broadcast_global({
                                "type": "system_event",
                                "event": data.get("event"),
                                "payload": data
                            })
                        except Exception as e:
                            logger.error(f"Error processing Redis broadcast: {e}")
            except Exception as e:
                logger.error(f"Redis subscriber loop error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(f"WebSocket connected to session {session_id}")

    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info(f"WebSocket disconnected from session {session_id}")

    async def broadcast_to_session(self, session_id: str, message: dict):
        """向指定会话的所有连接广播消息"""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_text(json.dumps(message, ensure_ascii=False))
                except Exception as e:
                    logger.error(f"Failed to broadcast to websocket in session {session_id}: {e}")

    async def broadcast_global(self, message: dict):
        """向所有连接广播全局消息 (如系统通知)"""
        for connections in self.active_connections.values():
            for connection in connections:
                try:
                    await connection.send_text(json.dumps(message, ensure_ascii=False))
                except Exception as e:
                    logger.error(f"Failed to broadcast global message: {e}")

# 全局连接管理器实例
manager_ws = ConnectionManager()

@router.websocket("/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    manager: SessionManager = Depends(get_session_manager)
):
    """
    流式推理 WebSocket 端点 (Phase 4 核心集成)。
    支持接收用户指令，并实时流回 Think-Act-Observe 全过程日志。
    """
    # 1. 握手阶段
    try:
        # FastAPI won't let us Depends inside the loop if we accept first, 
        # but here we need to accept to receive the first message.
        # Actually, we can accept then receive.
        await websocket.accept()
        initial_msg = await websocket.receive_text()
        data = json.loads(initial_msg)
        uid = data.get("uid")
        did = data.get("did")
        session_id_input = data.get("session_id")
        
        if not uid or not did:
            await websocket.send_text(json.dumps({"type": "error", "message": "Missing uid or did"}))
            await websocket.close()
            return

        session = manager.get_or_create_session(uid, did, session_id_input)
        session_id = session.id
        
        # 重新注册到连接管理器 (由于已经 accept 了，所以直接记录)
        if session_id not in manager_ws.active_connections:
            manager_ws.active_connections[session_id] = []
        manager_ws.active_connections[session_id].append(websocket)
        logger.info(f"New WebSocket connection established for session {session_id}")

        # 2. 初始化 AgentVM 和 历史记录
        vm = create_agent_vm(uid, did)
        history = manager.load_history(session_id)

        while True:
            # 3. 接收用户指令
            user_input = await websocket.receive_text()
            user_data = json.loads(user_input)
            message_text = user_data.get("message")
            
            if not message_text:
                continue

            user_msg = {"role": "user", "content": message_text}
            history.append(user_msg)
            manager.append_history(session_id, user_msg)
            
            # 4. 执行推理并流式回传
            try:
                async for chunk in vm.chat(history):
                    mapped_chunk = chunk.copy()
                    if chunk["type"] == "content":
                        mapped_chunk["type"] = "thought"
                    elif chunk["type"] == "tool_call":
                        mapped_chunk["type"] = "call"
                    elif chunk["type"] == "tool_result":
                        mapped_chunk["type"] = "observation"
                    
                    await websocket.send_text(json.dumps(mapped_chunk, ensure_ascii=False))
                    
                    if chunk["type"] == "message":
                        history.append(chunk["message"])
                        manager.append_history(session_id, chunk["message"])
                        
            except Exception as e:
                logger.error(f"Error during agent chat: {e}")
                await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))

    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for session {session_id if 'session_id' in locals() else 'unknown'}")
        if 'session_id' in locals():
            manager_ws.disconnect(session_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket session error: {e}")
        if 'session_id' in locals():
            manager_ws.disconnect(session_id, websocket)
        try:
            await websocket.close()
        except:
            pass
