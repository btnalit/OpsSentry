from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from src.ops_ledger import OpsLedger
from src.sandbox import SandboxProvider, create_sandbox_provider


class ToolRegistryError(RuntimeError):
    pass


class ToolNotRegistered(ToolRegistryError):
    pass


class ToolDisabled(ToolRegistryError):
    pass


@dataclass(slots=True)
class ToolResult:
    """工具执行结果封装"""
    success: bool
    output: str
    error: str | None = None
    audit_data: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """
    工具注册与审计中枢。
    实现 L1-L4 审计链与沙箱分发。
    """

    # L1: 全局禁用黑名单 (正则编译时开启 IGNORECASE)
    GLOBAL_DENY_PATTERNS = [
        re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
        re.compile(r"mkfs\.", re.IGNORECASE),
        re.compile(r"dd\s+if=", re.IGNORECASE),
        re.compile(r"chmod\s+777", re.IGNORECASE),
        re.compile(r"chown\s+root", re.IGNORECASE),
        re.compile(r">/dev/sd[a-z]", re.IGNORECASE),
    ]

    # L3: 需要审批的路径
    REQUIRE_APPROVAL_PATHS = [
        "/etc/nginx/nginx.conf",
        "/var/log/auth.log",
        "/root/",
        ".ssh/",
    ]

    def __init__(
        self, 
        ops_ledger: OpsLedger,
        sandbox: SandboxProvider | None = None,
        enabled_groups: dict[str, bool] | None = None
    ) -> None:
        self.ops_ledger = ops_ledger
        self.sandbox = sandbox or create_sandbox_provider()
        self.enabled_groups = enabled_groups or {}
        self._handlers: dict[str, Callable] = {}
        
        # 默认注册 bash/process
        self.register_tool("bash", self._dispatch_sandbox)
        self.register_tool("process", self._dispatch_sandbox)

    def register_tool(self, name: str, handler: Callable) -> None:
        self._handlers[name] = handler

    async def dispatch(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """工具分发主入口（含 4 层审计）"""
        
        # 1. 注册校验
        if tool_name not in self._handlers:
            raise ToolNotRegistered(tool_name)

        # 2. 角色准入校验 (L2)
        # 根据工具名推断其所属组
        group_name = self._get_tool_group(tool_name)
        if group_name and not self.enabled_groups.get(group_name, True):
            raise ToolDisabled(tool_name)

        # 3. 策略审计 (L1 & L3)
        if tool_name in ("bash", "process"):
            command = args.get("command", "")
            
            # L1: Global Deny
            if self._is_globally_denied(command):
                self.ops_ledger.create_entry(
                    action="tool_policy_blocked",
                    metadata={"tool": tool_name, "command": command, "reason": "L1 Global Deny"}
                )
                return {"blocked": True, "reason": "Security Violation: L1 Policy"}
            
            # L3: Require Approval
            if self._requires_approval(command):
                entry = self.ops_ledger.create_entry(
                    action="approval_required",
                    metadata={"tool": tool_name, "command": command, "reason": "L3 Path Approval"}
                )
                return {"pending_approval": entry.id}

        # 4. 执行 (L4)
        handler = self._handlers[tool_name]
        return await handler(args)

    async def _dispatch_sandbox(self, args: dict[str, Any]) -> dict[str, Any]:
        command = args.get("command", "")
        timeout = args.get("timeout", 30)
        workdir = args.get("workdir")
        env = args.get("env")
        
        # 记录 OpsLedger
        entry = self.ops_ledger.create_entry(
            action="sandbox_exec",
            metadata={"tool": "bash", "command": command}
        )
        self.ops_ledger.mark_running(entry.id)

        try:
            result = await self.sandbox.execute(
                command, 
                timeout_seconds=timeout, 
                workdir=workdir, 
                env=env
            )
            
            self.ops_ledger.mark_completed(
                entry.id, 
                checkpoint=result.to_audit_record()
            )

            outcome = {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated
            }
            
            if "permission denied" in result.stderr.lower():
                outcome["error"] = "Permission denied detected"
            
            return outcome
        except Exception as e:
            self.ops_ledger.mark_failed(entry.id, error=str(e))
            return {"error": str(e), "exit_code": -1}

    def _is_globally_denied(self, command: str) -> bool:
        """L1: 全局禁用黑名单校验 (正则 + 分词双重审计)"""
        # 1. 原始字符串正则扫描 (开启忽略大小写)
        if any(p.search(command) for p in self.GLOBAL_DENY_PATTERNS):
            return True

        # 2. 分词后精确匹配关键危险指令 (防止 rm-rf 这种混淆)
        try:
            tokens = [t.lower() for t in shlex.split(command)]
            danger_bins = {"rm", "mkfs", "dd", "chmod", "chown", "sh", "bash"}
            
            # 基础危险命令拦截
            if any(t in danger_bins for t in tokens):
                # 针对 rm / 的二次深度检查
                if "rm" in tokens and "/" in tokens:
                    return True
                # 针对 chmod 777 的二次深度检查
                if "chmod" in tokens and "777" in tokens:
                    return True
            
            # 针对 管道/重定向 + Shell 的绕过拦截
            if "|" in tokens or ";" in tokens or "&" in tokens:
                if any(shell in tokens for shell in ("sh", "bash")):
                    return True
                    
        except ValueError:
            # 解析失败则保守起见拦截
            return True

        return False

    def _requires_approval(self, command: str) -> bool:
        """L3: 关键路径审批校验 (通过 shlex 分词与路径规范化)"""
        try:
            tokens = shlex.split(command)
        except ValueError:
            # 解析失败则保守起见拦截
            return True

        for token in tokens:
            # 检查分词是否包含敏感路径，或其 resolve 后的绝对路径匹配
            for p in self.REQUIRE_APPROVAL_PATHS:
                if p in token:
                    return True
                try:
                    # 尝试将 token 作为路径解析，检查其 resolve 后的前缀
                    resolved = Path(token).resolve()
                    if str(resolved).startswith(str(Path(p).resolve())):
                        return True
                except Exception:
                    continue
        return False

    def _get_tool_group(self, tool_name: str) -> str | None:
        # 硬编码映射，对齐 agent_manager.py
        mapping = {
            "bash": "command_execution",
            "process": "command_execution",
            "list": "file_system",
            "read": "file_system",
            "grep": "file_system",
            "glob": "file_system",
            "ripgrep": "file_system",
            "write": "file_system",
            "edit": "file_system",
            "web_fetch": "network_probe",
            "cron": "cron_trigger",
            "question": "human_confirm",
            "memory_search": "memory_planning",
            "memory_get": "memory_planning",
            "task_create": "memory_planning",
            "task_get": "memory_planning",
            "task_update": "memory_planning",
            "task_list": "memory_planning",
            "sessions_spawn": "agent_collaboration",
            "sessions_list": "agent_collaboration",
            "sessions_history": "agent_collaboration",
            "sessions_send": "agent_collaboration",
            "mcp_call": "external_integration",
            "listen_gmail_reply": "notification",
            "unlisten_gmail": "notification",
        }
        return mapping.get(tool_name)
