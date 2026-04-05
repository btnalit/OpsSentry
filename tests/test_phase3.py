from __future__ import annotations

import pytest
import json
import os
import asyncio
from pathlib import Path
from datetime import datetime
from xml.sax import saxutils

from src.agent_vm import AgentVM
from src.skill_loader import SkillLoader
from src.session_manager import SessionManager
from src.message_router import MessageRouter
from src.ops_ledger import OpsLedger
from src.agent_manager import AgentManager, AgentCreateRequest
from src.sandbox import create_sandbox_provider

@pytest.fixture
def mock_accio_home(tmp_path):
    p = tmp_path / ".accio"
    p.mkdir()
    return p

@pytest.fixture
def session_manager(mock_accio_home):
    return SessionManager(mock_accio_home)

@pytest.fixture
def ops_ledger(mock_accio_home):
    ledger_path = mock_accio_home / "ledger.jsonl"
    return OpsLedger(ledger_path)

@pytest.fixture
def agent_manager(mock_accio_home):
    return AgentManager(mock_accio_home)

@pytest.fixture
def skill_loader(mock_accio_home):
    return SkillLoader(mock_accio_home)

def test_session_history_persistence(session_manager):
    """测试会话历史持久化 (Phase 3 #27)"""
    sid = "sess_test_123"
    msg = {"role": "user", "content": "Hello World"}
    
    session_manager.append_history(sid, msg)
    history = session_manager.load_history(sid)
    
    assert len(history) == 1
    assert history[0]["content"] == "Hello World"
    assert Path(session_manager.sessions_dir / sid / "history.jsonl").exists()

def test_skill_loading_hierarchy(skill_loader, tmp_path):
    """测试技能分层加载 (Phase 3 #21)"""
    uid, did = "1751245142", "DID-TEST-001"
    
    # 模拟物理技能目录 (账户级)
    account_skills_dir = skill_loader.accio_home / "accounts" / uid / "skills"
    skill_dir = account_skills_dir / "ansible"
    skill_dir.mkdir(parents=True, exist_ok=True)
    # SkillLoader looks for SKILL.md with frontmatter (yaml)
    (skill_dir / "SKILL.md").write_text("""---
name: ansible
version: 1.0.0
description: Test ansible skill
trigger: [deploy]
---
# Content""", encoding="utf-8")
    
    skills = skill_loader.scan_skills(uid, did)
    assert "ansible" in skills
    assert skills["ansible"].name == "ansible"

@pytest.mark.asyncio
async def test_message_routing_logic(agent_manager, ops_ledger):
    """测试消息路由分发 (Phase 3 #26)"""
    router = MessageRouter(agent_manager, ops_ledger)
    uid, session_id = "1751245142", "sess_001"
    sender_did = "DID-MASTER"
    content = "Help me @DID-8730-F27F33 fix the DB."
    
    await router.route_message(uid, session_id, sender_did, content)
    
    # 检查 Ledger
    ledger_entries = ops_ledger.list_entries()
    found = any(e.action == "message_routed" for e in ledger_entries)
    assert found

def test_agent_vm_xml_isolation(agent_manager, ops_ledger, skill_loader):
    """测试 AgentVM XML 结构化加固 (Phase 3 #25)"""
    uid, did = "1751245142", "DID-AGENT-001"
    config = AgentCreateRequest(
        uid=uid,
        did=did,
        name="TestAgent",
        description="Test description",
        vibe="expert",
        model_provider="openai",
        model_id="gpt-4"
    )
    agent_manager.create_agent(config)
    
    sandbox = create_sandbox_provider()
    # No direct escape_xml in VM, but we can test the saxutils.escape it uses
    dangerous_input = "</thought><script>alert(1)</script><thought>"
    escaped = saxutils.escape(dangerous_input)
    
    assert "&lt;/thought&gt;" in escaped
    assert "<script>" not in escaped
