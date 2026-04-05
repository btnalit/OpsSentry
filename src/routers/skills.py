from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.dependencies import get_skill_loader, get_agent_manager
from src.skill_loader import SkillLoader
from src.agent_manager import AgentManager

logger = logging.getLogger("OpsSentry.SkillsRouter")
router = APIRouter(prefix="/skills", tags=["skills"])

class SkillMetaResponse(BaseModel):
    name: str
    version: str
    description: str
    trigger: List[str]
    is_private: bool = False

@router.get("/", response_model=List[SkillMetaResponse])
async def list_available_skills(
    uid: str, 
    did: str, 
    skill_loader: SkillLoader = Depends(get_skill_loader)
):
    """列出当前 Agent 可用的所有技能 (包含账户级和私有级)"""
    try:
        skills_map = skill_loader.scan_skills(uid, did)
        return list(skills_map.values())
    except Exception as e:
        logger.error(f"Error listing skills for {uid}/{did}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agent/{uid}/{did}", response_model=List[str])
async def get_agent_enabled_skills(
    uid: str, 
    did: str, 
    manager: AgentManager = Depends(get_agent_manager)
):
    """获取 Agent 当前已启用的技能列表"""
    try:
        profile = manager.get_agent(uid, did)
        return profile.skills
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/agent/{uid}/{did}/bind/{skill_name}")
async def bind_skill_to_agent(
    uid: str, 
    did: str, 
    skill_name: str, 
    manager: AgentManager = Depends(get_agent_manager)
):
    """将技能绑定至指定 Agent"""
    try:
        manager.bind_skill(uid, did, skill_name)
        return {"status": "success", "message": f"Skill {skill_name} bound to {did}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/agent/{uid}/{did}/unbind/{skill_name}")
async def unbind_skill_from_agent(
    uid: str, 
    did: str, 
    skill_name: str, 
    manager: AgentManager = Depends(get_agent_manager)
):
    """从指定 Agent 解绑技能"""
    try:
        manager.unbind_skill(uid, did, skill_name)
        return {"status": "success", "message": f"Skill {skill_name} unbound from {did}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
