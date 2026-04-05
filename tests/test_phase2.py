from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
import pytest

from src.agent_manager import AgentCreateRequest, AgentManager, AgentNotFoundError, InvalidCoreFileError


class _AssertRaises:
    def __init__(self, expected_exception):
        self.expected_exception = expected_exception

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_type:
            pytest.fail(f"DID NOT RAISE {self.expected_exception}")
        if not issubclass(exc_type, self.expected_exception):
            pytest.fail(f"RAISED {exc_type} instead of {self.expected_exception}")
        return True


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmp:
        yield AgentManager(Path(tmp))


def test_agent_manager_creates_and_retrieves_agent(manager):
    request = AgentCreateRequest(
        uid="U123",
        name="SecurityBot",
        description="Auditing bot",
        vibe="expert",
        model_provider="claude",
        model_id="claude-3-opus"
    )
    profile = manager.create_agent(request)
    assert profile.uid == "U123"
    assert profile.name == "SecurityBot"
    assert profile.did.startswith("DID-")

    retrieved = manager.get_agent("U123", profile.did)
    assert retrieved.did == profile.did
    assert retrieved.uid == "U123"


def test_path_traversal_protection(manager):
    """[安全审计] 测试路径穿越防护"""
    request = AgentCreateRequest(
        uid="U123", name="Bot", description=".", vibe="expert", model_provider="claude", model_id="c1"
    )
    created = manager.create_agent(request)
    
    # 尝试通过 DID 注入路径穿越
    with _AssertRaises(Exception): # AgentManager should block DID-../../ format
        manager.get_agent("U123", "DID-../../bad_path")

    # 尝试读取核心文件之外的文件
    with _AssertRaises(InvalidCoreFileError):
        manager.read_core_file("U123", created.did, "../../../etc/passwd")


def test_cross_user_did_access_prevention(manager):
    """[安全审计] 测试跨用户 DID 越权防护"""
    # 用户 A 创建 Agent
    req_a = AgentCreateRequest(uid="User-A", name="Agent-A", description=".", vibe="expert", model_provider="claude", model_id="c1")
    profile_a = manager.create_agent(req_a)
    
    # 用户 B 尝试读取 用户 A 的 Agent
    # 即使知道 DID，由于 UID 不匹配，应该报错
    with _AssertRaises((AgentNotFoundError, PermissionError)): 
        manager.get_agent("User-B", profile_a.did)
    
    # 尝试直接读取核心文件
    with _AssertRaises((AgentNotFoundError, PermissionError)):
        manager.read_core_file("User-B", profile_a.did, "SOUL.md")


def test_agent_manager_binds_unbinds_skills(manager):
    request = AgentCreateRequest(uid="U1", name="B", description=".", vibe="expert", model_provider="claude", model_id="c1")
    p = manager.create_agent(request)
    
    manager.bind_skill("U1", p.did, "network-scanner")
    assert "network-scanner" in manager.get_agent("U1", p.did).skills
    
    manager.unbind_skill("U1", p.did, "network-scanner")
    assert "network-scanner" not in manager.get_agent("U1", p.did).skills


def test_agent_deletion(manager):
    request = AgentCreateRequest(uid="U1", name="B", description=".", vibe="expert", model_provider="claude", model_id="c1")
    p = manager.create_agent(request)
    
    manager.delete_agent("U1", p.did)
    with _AssertRaises(AgentNotFoundError):
        manager.get_agent("U1", p.did)
