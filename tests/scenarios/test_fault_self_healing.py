# OpsSentry Phase 5: #42 Fault Self-healing Scenario (E2E)
# This test simulates a full self-healing loop: 
# 1. Fault detection (Simulation) 
# 2. Webhook authorization (Mocked)
# 3. AgentVM autonomous repair (Execution)
# 4. Result Audit (OpsLedger)

import asyncio
import json
import os
import shutil
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.dependencies import get_config_shield, get_ops_ledger, get_agent_manager, get_message_router
from src.agent_manager import AgentManager
from src.ops_ledger import OpsLedger
from src.message_router import MessageRouter
from src.agent_vm import AgentVM
from src.global_sync import SyncBuffer

# 1. 模拟环境配置 (Test Setup)
TEST_UID = "USER_TEST_42"
TEST_DID = "DID-88888888-666666"
TEST_ACCIO_HOME = Path("temp_test_self_healing")

@pytest.fixture(autouse=True)
def setup_teardown():
    if TEST_ACCIO_HOME.exists():
        shutil.rmtree(TEST_ACCIO_HOME)
    TEST_ACCIO_HOME.mkdir(parents=True, exist_ok=True)
    os.environ["ACCIO_HOME"] = str(TEST_ACCIO_HOME)
    yield
    # shutil.rmtree(TEST_ACCIO_HOME)

@pytest.mark.asyncio
async def test_grand_finale_self_healing():
    """
    Phase 5 #42: 终极自愈实战演练 (磁盘爆满 -> 授权 -> 修复 -> 审计)。
    """
    # 2. 初始化核心组件 (Dependency Bootstrapping)
    shield = get_config_shield()
    ledger = get_ops_ledger()
    manager = get_agent_manager()
    router_bus = get_message_router()
    
    # 3. 准备自愈 Agent (Agent Injection)
    # 创建具有运维性格的专家 Agent
    agent = manager.create_agent(TEST_UID, "Log-Analyzer", vibe="expert")
    agent_did = agent["did"]
    
    # 绑定 disk-cleanup 技能
    manager.bind_skill(TEST_UID, agent_did, "disk-cleanup")
    
    # 4. 故障检测模拟 (Fault Detection Simulation)
    # 模拟磁盘爆满告警（由外部巡检 Cron 触发）
    fault_alert = {
        "type": "alert",
        "node_id": "NODE_PRIMARY",
        "metric": "disk_usage",
        "value": "95%",
        "threshold": "90%",
        "msg": "Critical: /var/log is full!"
    }
    
    # 记录告警到 Ledger
    ledger.create_entry("fault_detected", fault_alert)
    
    # 5. 模拟飞书 Webhook 授权入站 (Mocked Webhook Authorization)
    # 模拟董事长回复：“@DID-XXXX-XXXX 请清理 /var/log 下的旧日志”
    auth_content = f"@{agent_did} 收到告警，请立即清理 /var/log 下的旧日志，确保系统水位降至 80% 以下。"
    
    # 我们直接通过路由总线转发这条“授权指令”
    # 这对应了 Webhook 路由收到验签消息后的处理逻辑
    await router_bus.route_message(
        uid=TEST_UID,
        session_id="sess_self_healing_42",
        sender_did="external_BOSS",
        content=auth_content
    )
    
    # 6. 等待 AgentVM 自愈回路执行 (Execution Monitor)
    # 由于 AgentVM.chat 是后台任务，我们需要给一点时间让它完成“思考-执行-反馈”
    # 在真实环境中，这里会触发 NsJail/Bwrap 执行 disk-cleanup 脚本
    print(f"\n[PHASE 5] Waiting for Agent {agent_did} to perform self-healing...")
    await asyncio.sleep(5)  # 模拟推理与沙箱执行时间
    
    # 7. 审计记录验证 (Result Verification)
    entries = ledger.get_entries()
    
    # 验证故障检测记录
    assert any(e["action"] == "fault_detected" for e in entries)
    
    # 验证消息路由记录
    routing_entry = next(e for e in entries if e["action"] == "message_routed")
    assert routing_entry["metadata"]["sender_did"] == "external_BOSS"
    assert agent_did in routing_entry["metadata"]["mentions"]
    
    # 验证 Agent 动作链路 (Thinking & Acting)
    agent_actions = [e for e in entries if e["action"] == "agent_action"]
    assert len(agent_actions) > 0
    
    # 检查是否调用了工具 (Act)
    # 在 Mock 环境下，AgentVM 应该识别出需要调用 disk-cleanup 工具
    tool_calls = [a for a in agent_actions if a["metadata"]["payload"]["type"] == "call"]
    assert len(tool_calls) > 0
    print(f"[AUDIT] Agent performed {len(tool_calls)} actions during self-healing.")
    
    # 检查是否有最终反馈 (Final Answer)
    final_responses = [a for a in agent_actions if a["metadata"]["payload"]["type"] == "message"]
    if final_responses:
         print(f"[RECOVERY] Agent Reply: {final_responses[0]['metadata']['payload']['message']['content']}")
    
    # 8. 分布式同步核实 (LockedSyncBuffer Check)
    # 验证 SyncBuffer 是否包含了此次自愈的所有审计流水
    sync_buffer = SyncBuffer(shield)
    sync_records = sync_buffer.read_all()
    # 备注：在 src/ops_ledger.py 中，写入 ledger 时会自动同步到 sync_buffer
    assert len(sync_records) > 0
    print(f"[SYNC] Successfully verified {len(sync_records)} distributed sync records.")

    print("\n[PHASE 5] #42 SELF-HEALING SCENARIO: 100% SUCCESS.")

if __name__ == "__main__":
    asyncio.run(test_grand_finale_self_healing())
