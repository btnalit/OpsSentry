from fastapi import APIRouter, HTTPException, Depends, Header
from typing import List, Dict, Any
import os
from src.agent_manager import AgentManager, AgentCreateRequest, AgentProfile
from src.dependencies import get_agent_manager
from src.auth import get_current_user, require_role, verify_resource_ownership, CurrentUser

router = APIRouter(prefix="/agents", tags=["agents"])

async def get_resource_uid(uid: str, user: CurrentUser = Depends(get_current_user)) -> str:
    """IDOR 防护校验：确保请求中的 uid 与 JWT 中的 user_id 匹配 (Phase 8 #70.2)"""
    return verify_resource_ownership(uid, user)

@router.post("/", response_model=AgentProfile)
async def create_agent(
    request: AgentCreateRequest, 
    user: CurrentUser = Depends(require_role(["admin", "operator"])), 
    manager: AgentManager = Depends(get_agent_manager)
):
    # 强制验证创建请求中的 UID 与请求者身份一致
    verify_resource_ownership(request.uid, user)
    try:
        return manager.create_agent(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{uid}", response_model=List[AgentProfile])
async def list_agents(uid: str = Depends(get_resource_uid), manager: AgentManager = Depends(get_agent_manager)):
    try:
        return manager.list_agents(uid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{uid}/{did}", response_model=AgentProfile)
async def get_agent(uid: str = Depends(get_resource_uid), did: str = None, manager: AgentManager = Depends(get_agent_manager)):
    try:
        return manager.get_agent(uid, did)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{uid}/{did}", response_model=AgentProfile)
async def update_agent(
    uid: str = Depends(get_resource_uid), 
    did: str = None, 
    update: Dict[str, Any] = None, 
    user: CurrentUser = Depends(require_role(["admin", "operator"])),
    manager: AgentManager = Depends(get_agent_manager)
):
    try:
        return manager.update_agent(uid, did, update)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{uid}/{did}")
async def delete_agent(
    uid: str = Depends(get_resource_uid), 
    did: str = None, 
    user: CurrentUser = Depends(require_role(["admin", "operator"])),
    manager: AgentManager = Depends(get_agent_manager)
):
    try:
        manager.delete_agent(uid, did)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{uid}/{did}/core/{filename}")
async def read_core_file(uid: str = Depends(get_resource_uid), did: str = None, filename: str = None, manager: AgentManager = Depends(get_agent_manager)):
    try:
        content = manager.read_core_file(uid, did, filename)
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{uid}/{did}/skills/{skill_id}")
async def bind_skill(
    uid: str = Depends(get_resource_uid), 
    did: str = None, 
    skill_id: str = None, 
    user: CurrentUser = Depends(require_role(["admin", "operator"])),
    manager: AgentManager = Depends(get_agent_manager)
):
    try:
        manager.bind_skill(uid, did, skill_id)
        return {"status": "bound", "skill_id": skill_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{uid}/{did}/skills/{skill_id}")
async def unbind_skill(
    uid: str = Depends(get_resource_uid), 
    did: str = None, 
    skill_id: str = None, 
    user: CurrentUser = Depends(require_role(["admin", "operator"])),
    manager: AgentManager = Depends(get_agent_manager)
):
    try:
        manager.unbind_skill(uid, did, skill_id)
        return {"status": "unbound", "skill_id": skill_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{uid}/{did}/exec")
async def execute_agent(
    uid: str = Depends(get_resource_uid),
    did: str = None,
    payload: Dict[str, Any] = None,
    user: CurrentUser = Depends(require_role(["admin", "operator"])),
    manager: AgentManager = Depends(get_agent_manager)
):
    """
    Phase 8 #70.3: RBAC 鉴权集成测试端点。
    验证 Operator/Admin 角色是否具备执行权限。
    """
    return {"status": "executed", "node": os.environ.get("OPSSENTRY_NODE_ID", "default-node"), "agent": f"{uid}/{did}"}
