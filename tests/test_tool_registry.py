from __future__ import annotations

import pytest

from ops_ledger import OpsLedger
from sandbox import SandboxResult
from tool_registry import ToolDisabled, ToolNotRegistered, ToolRegistry


class StubSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def execute(self, command: str, *, timeout_seconds: int = 30, workdir: str | None = None, env: dict[str, str] | None = None, network: bool = False) -> SandboxResult:
        self.calls.append(
            {
                "command": command,
                "timeout_seconds": timeout_seconds,
                "workdir": workdir,
                "env": env,
                "network": network,
            }
        )
        return self.result

    def mode_name(self) -> str:
        return self.result.sandbox_mode


@pytest.mark.asyncio
async def test_policy_l1_deny_blocks_execution(tmp_path):
    ledger = OpsLedger(tmp_path / "ledger.jsonl")
    sandbox = StubSandbox(SandboxResult(exit_code=0, stdout="ok", stderr="", duration_ms=12))
    registry = ToolRegistry(sandbox=sandbox, ops_ledger=ledger)

    outcome = await registry.dispatch("bash", {"command": "rm -rf /"})

    assert outcome["blocked"] is True
    assert sandbox.calls == []
    blocked_entries = ledger.list_entries()
    assert blocked_entries[-1].action == "tool_policy_blocked"


@pytest.mark.asyncio
async def test_policy_l3_returns_pending_approval(tmp_path):
    ledger = OpsLedger(tmp_path / "ledger.jsonl")
    sandbox = StubSandbox(SandboxResult(exit_code=0, stdout="ok", stderr="", duration_ms=12))
    registry = ToolRegistry(sandbox=sandbox, ops_ledger=ledger)

    outcome = await registry.dispatch("bash", {"command": "cat /etc/nginx/nginx.conf"})

    assert "pending_approval" in outcome
    assert sandbox.calls == []
    approval_entry = ledger.get_entry(outcome["pending_approval"])
    assert approval_entry.action == "approval_required"


@pytest.mark.asyncio
async def test_safe_command_executes_and_writes_audit_entry(tmp_path):
    ledger = OpsLedger(tmp_path / "ledger.jsonl")
    sandbox = StubSandbox(SandboxResult(exit_code=0, stdout="filesystem ok\n", stderr="", duration_ms=9, sandbox_mode="direct"))
    registry = ToolRegistry(sandbox=sandbox, ops_ledger=ledger)

    outcome = await registry.dispatch("bash", {"command": "df -h", "timeout": 7, "workdir": str(tmp_path)})

    assert outcome["stdout"] == "filesystem ok\n"
    assert sandbox.calls[0]["timeout_seconds"] == 7
    assert sandbox.calls[0]["workdir"] == str(tmp_path)
    entries = ledger.list_entries()
    assert entries[-1].action == "sandbox_exec"
    assert entries[-1].metadata["command"] == "df -h"


@pytest.mark.asyncio
async def test_permission_denied_is_reported_after_execution(tmp_path):
    ledger = OpsLedger(tmp_path / "ledger.jsonl")
    sandbox = StubSandbox(SandboxResult(exit_code=1, stdout="", stderr="Permission denied", duration_ms=5))
    registry = ToolRegistry(sandbox=sandbox, ops_ledger=ledger)

    outcome = await registry.dispatch("bash", {"command": "cat ./secret.txt"})

    assert outcome["error"] == "Permission denied detected"
    assert outcome["exit_code"] == 1


@pytest.mark.asyncio
async def test_unregistered_and_disabled_tools_raise(tmp_path):
    registry = ToolRegistry(
        sandbox=StubSandbox(SandboxResult(exit_code=0, stdout="", stderr="", duration_ms=1)),
        ops_ledger=OpsLedger(tmp_path / "ledger.jsonl"),
        enabled_groups={"network_probe": False},
    )

    with pytest.raises(ToolNotRegistered):
        await registry.dispatch("nonexistent", {})

    with pytest.raises(ToolDisabled):
        await registry.dispatch("web_fetch", {"urls": ["https://example.com"]})


@pytest.mark.asyncio
async def test_registered_non_command_tool_dispatches_handler(tmp_path):
    registry = ToolRegistry(
        sandbox=StubSandbox(SandboxResult(exit_code=0, stdout="", stderr="", duration_ms=1)),
        ops_ledger=OpsLedger(tmp_path / "ledger.jsonl"),
    )

    async def fake_tool(args: dict[str, object]) -> dict[str, object]:
        return {"echo": args["message"]}

    registry.register_tool("task_list", fake_tool)
    outcome = await registry.dispatch("task_list", {"message": "ping"})

    assert outcome == {"echo": "ping"}
