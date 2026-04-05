# AgentVM 环境变量隔离方案 & tool-registry.jsonc 存储规格

> **文档版本**：v1.0 | **最后更新**：2026-03-31
> **作者**：Architect (系统架构师)
> **依赖**：SDD v2.1 §3.2/§3.3/§3.10、SandboxProvider_Design.md、ToolRegistry_AuditChain_Spec.md

---

## Part A: AgentVM LiteLLM API Key 环境变量隔离方案

### A.1 问题陈述

QA 审计报告（Audit_Report_Phase2_Env.md）标记 **[高危]**：

> LiteLLM 通过 `os.environ` 读取 API Key（如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`）。
> 当多个 Agent 共存于同一进程时，所有 Agent 共享进程级环境变量。
> 若不同 Agent 使用不同 model_provider 或不同账户的 Key，存在：
> 1. **Key 污染**：Agent A 设置的 Key 被 Agent B 的推理调用读取
> 2. **Key 泄露**：Agent 通过 `bash` 工具执行 `echo $OPENAI_API_KEY` 获取明文 Key

### A.2 隔离架构

```mermaid
graph TD
    subgraph AgentVM
        A1[Agent A 推理回路]
        A2[Agent B 推理回路]
    end

    subgraph KeyVault
        V[AgentKeyVault]
        V -->|agent_did → key_set| K1["Agent A Keys"]
        V -->|agent_did → key_set| K2["Agent B Keys"]
    end

    subgraph LiteLLM_Adapter
        L[LiteLLMAdapter]
    end

    A1 -->|did=A| L
    A2 -->|did=B| L
    L -->|lookup(did)| V
    L -->|api_key=xxx| LITELLM[litellm.acompletion]
```

### A.3 AgentKeyVault（密钥保险柜）

**文件**：`src/agent_key_vault.py`

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class AgentKeySet:
    """单个 Agent 的 API Key 集合（不可变）"""
    agent_did: str
    provider: str                          # "openai" | "claude" | "qwen" | ...
    api_key: str                           # 核心密钥
    api_base: str | None = None            # 自定义 endpoint
    extra: dict[str, str] = field(default_factory=dict)  # 附加参数


class AgentKeyVault:
    """
    Agent 级 API Key 隔离存储。
    
    密钥来源优先级（高→低）：
    1. Agent 级配置文件：~/.accio/accounts/{uid}/agents/{did}/agent-core/secrets.json
    2. 账户级配置文件：~/.accio/accounts/{uid}/secrets.json
    3. 全局环境变量（fallback）：os.environ["OPENAI_API_KEY"] 等
    
    安全约束：
    - secrets.json 文件权限必须为 0o600（仅 owner 可读写）
    - secrets.json 必须在 .gitignore / .dockerignore 中排除
    - 不在 agent_config.json 中存储任何密钥
    """

    # provider → 环境变量名的映射（fallback 用）
    _ENV_KEY_MAP: dict[str, str] = {
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "zhipu": "ZHIPU_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }

    def __init__(self, accio_home: str | Path) -> None:
        self._accio_home = Path(accio_home)

    def resolve_keys(self, uid: str, did: str, provider: str) -> AgentKeySet:
        """
        按优先级链解析 Agent 的 API Key。
        
        Returns
        -------
        AgentKeySet
            解析后的密钥集合（frozen，防止运行时篡改）
            
        Raises
        ------
        KeyError
            所有来源均无法找到有效密钥
        """
        # Priority 1: Agent 级 secrets.json
        agent_secrets = self._load_secrets(
            self._accio_home / "accounts" / uid / "agents" / did / "agent-core" / "secrets.json"
        )
        if agent_secrets and provider in agent_secrets:
            return self._build_key_set(did, provider, agent_secrets[provider])

        # Priority 2: 账户级 secrets.json
        account_secrets = self._load_secrets(
            self._accio_home / "accounts" / uid / "secrets.json"
        )
        if account_secrets and provider in account_secrets:
            return self._build_key_set(did, provider, account_secrets[provider])

        # Priority 3: 全局环境变量 (fallback)
        env_var = self._ENV_KEY_MAP.get(provider, "")
        env_val = os.environ.get(env_var, "") if env_var else ""
        if env_val:
            return AgentKeySet(agent_did=did, provider=provider, api_key=env_val)

        raise KeyError(
            f"No API key found for agent={did}, provider={provider}. "
            f"Checked: agent secrets, account secrets, env ${env_var}"
        )

    @staticmethod
    def _load_secrets(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _build_key_set(did: str, provider: str, config: dict[str, str]) -> AgentKeySet:
        return AgentKeySet(
            agent_did=did,
            provider=provider,
            api_key=config["api_key"],
            api_base=config.get("api_base"),
            extra={k: v for k, v in config.items() if k not in ("api_key", "api_base")},
        )
```

### A.4 LiteLLMAdapter（推理调用适配器）

**关键设计**：绝不写 `os.environ`。所有 API Key 通过 `litellm.acompletion()` 的参数传入。

```python
# src/agent_vm.py 中调用 LiteLLM 的方式（伪代码）

import litellm

class AgentVM:
    def __init__(self, key_vault: AgentKeyVault, ...):
        self._key_vault = key_vault

    async def _call_llm(self, agent: AgentProfile, messages: list[dict]) -> str:
        # 从 KeyVault 获取当前 Agent 的专属 Key
        key_set = self._key_vault.resolve_keys(
            uid=agent.uid,
            did=agent.did,
            provider=agent.model_provider,
        )

        # 直接通过参数传入，不污染 os.environ
        response = await litellm.acompletion(
            model=f"{key_set.provider}/{agent.model_id}",
            messages=messages,
            api_key=key_set.api_key,
            api_base=key_set.api_base,
            # 不设置 os.environ，完全参数化
        )
        return response.choices[0].message.content
```

### A.5 防泄露措施（sandbox 层）

**问题**：即使 KeyVault 不写 `os.environ`，全局环境变量（Priority 3 fallback）仍然存在于进程空间。Agent 可通过 `bash` 工具执行 `env` / `printenv` / `echo $OPENAI_API_KEY` 获取。

**防御方案**（三道防线）：

| 层级 | 措施 | 实现位置 |
|---|---|---|
| **L3 Policy** | 新增 Policy 规则，deny 所有读取环境变量的命令 | `config/policy-default.jsonl` |
| **DirectRunner** | 执行命令时，传入 **净化后的 env**，仅保留白名单变量 | `src/sandbox.py` DirectRunner.execute() |
| **NsJailRunner** | `env_whitelist` 已限制为 `LANG/PATH/HOME` | SDD §3.10 已覆盖 |

**新增 Policy 规则**（追加到 `config/policy-default.jsonl`）：

```json
{"level":"L1","effect":"deny","match":{"command_regex":"(printenv|\\benv\\b|\\$[A-Z_]*KEY|\\$[A-Z_]*SECRET|\\$[A-Z_]*TOKEN|\\$[A-Z_]*PASSWORD)"},"reason":"environment variable key/secret access denied"}
```

**DirectRunner 环境净化**：

```python
# DirectRunner.execute() 中构造子进程 env 的逻辑
_ENV_WHITELIST = {"PATH", "HOME", "LANG", "TERM", "PYTHONPATH", "TMP", "TEMP"}

def _build_clean_env(self, extra_env: dict[str, str] | None) -> dict[str, str]:
    """仅传入白名单环境变量，阻断 API Key 泄露"""
    clean = {k: v for k, v in os.environ.items() if k in self._ENV_WHITELIST}
    if extra_env:
        clean.update(extra_env)
    return clean
```

### A.6 secrets.json 格式约定

```json
{
  "openai": {
    "api_key": "sk-xxxxxxxxxxxx",
    "api_base": "https://api.openai.com/v1"
  },
  "claude": {
    "api_key": "sk-ant-xxxxxxxxxxxx"
  },
  "qwen": {
    "api_key": "sk-xxxxxxxxxxxx",
    "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  }
}
```

**安全规则**：
- 文件权限：`chmod 600 secrets.json`（Linux/macOS），Windows 使用 ACL
- `.gitignore` 必须包含 `**/secrets.json`
- `.dockerignore` 必须包含 `**/secrets.json`
- Docker 构建时通过 `--secret` 挂载，不 COPY 进镜像

---

## Part B: tool-registry.jsonc 存储格式审阅

### B.1 当前问题

`AgentManager._write_json()` 使用 `json.dumps()` 写入 `tool-registry.jsonc` 文件。但 `.jsonc` 格式允许 `//` 注释，而 `json.dumps()` 无法保留注释。

SDD §3.3 中的 `tool-registry.jsonc` 模板包含大量 `//` 注释（用于解释每个工具组的用途），这些注释具有运维文档价值。

### B.2 设计决策：使用纯 JSON，放弃 JSONC 注释保留

**理由**：

1. **Python stdlib `json` 模块不支持 JSONC**。引入第三方 JSONC 解析库（如 `json5`、`commentjson`）增加依赖复杂度，与项目"最小依赖"原则矛盾。
2. **tool-registry.jsonc 是机器生成文件**（由 `AgentManager._build_tool_registry()` 生成），不是人工编辑的配置。注释的文档价值可以通过 SDD 和 IDENTITY.md 覆盖。
3. **运行时只关心 `enabled_groups` 的布尔值**，工具组定义已硬编码在 `DEFAULT_TOOL_GROUPS` 常量中。

### B.3 存储规格

**文件名**：保持 `tool-registry.jsonc` 不变（与 Accio 原生路径对齐）

**读取方式**：

```python
import json
import re

def read_jsonc(path: Path) -> dict:
    """读取 JSONC 文件，剥离 // 注释后解析为 JSON"""
    text = path.read_text(encoding="utf-8")
    # 剥离单行注释（// ...），但不剥离 URL 中的 //
    stripped = re.sub(r'(?<!:)//.*?$', '', text, flags=re.MULTILINE)
    return json.loads(stripped)
```

**写入方式**：

```python
def write_tool_registry(path: Path, data: dict) -> None:
    """写入 tool-registry.jsonc，追加人类可读头注释"""
    header = (
        "// OpsSentry tool-registry.jsonc\n"
        "// Auto-generated by AgentManager. Do not edit manually.\n"
        "// Tool group definitions: see SDD §3.3\n"
    )
    json_body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    content = header + json_body + "\n"
    # 使用原子写入（临时文件 + os.replace）
    _atomic_write(path, content)
```

### B.4 格式示例（写入后的文件内容）

```jsonc
// OpsSentry tool-registry.jsonc
// Auto-generated by AgentManager. Do not edit manually.
// Tool group definitions: see SDD §3.3
{
  "denied_tools": [
    "get_location",
    "get_weather",
    "image_edit",
    "image_generate",
    "product_supplier_search",
    "see_image",
    "web_search"
  ],
  "enabled_groups": {
    "agent_collaboration": true,
    "command_execution": true,
    "cron_trigger": true,
    "external_integration": true,
    "file_system": true,
    "human_confirm": false,
    "memory_planning": true,
    "network_probe": true,
    "notification": true
  },
  "tool_groups": {
    "agent_collaboration": ["sessions_spawn", "sessions_list", "sessions_history", "sessions_send"],
    "command_execution": ["bash", "process"],
    "cron_trigger": ["cron"],
    "external_integration": ["mcp_call"],
    "file_system": ["list", "read", "grep", "glob", "ripgrep", "write", "edit"],
    "human_confirm": ["question"],
    "memory_planning": ["memory_search", "memory_get", "task_create", "task_get", "task_update", "task_list"],
    "network_probe": ["web_fetch"],
    "notification": ["listen_gmail_reply", "unlisten_gmail"]
  }
}
```

### B.5 Developer 编码约束

1. `AgentManager._write_json()` 对 `tool-registry.jsonc` 文件特殊处理：追加 3 行 `//` 头注释
2. `AgentManager._read_json()` 或 `ToolRegistry` 读取 `.jsonc` 时，先用 `re.sub` 剥离 `//` 注释
3. **不引入** `json5` / `commentjson` 等第三方依赖
4. `tool_groups` 字段仅用于参考，运行时 `ToolRegistry` 以 `DEFAULT_TOOL_GROUPS` 硬编码为准（single source of truth）
5. `read_jsonc()` 的注释剥离正则必须处理 URL 中的 `//`（如 `https://`），使用 `(?<!:)//` lookbehind

---

## Part C: ToolRegistry 四层审计链监控清单（持续审视）

结合本次审阅，在已有 7 个断点（C-1 ~ C-7，见 ToolRegistry_AuditChain_Spec.md §9）基础上，新增 2 个安全审计断点：

| # | 检查项 | 验证方式 |
|---|---|---|
| **C-8** | LiteLLM 调用禁止写 `os.environ`，必须参数化传入 `api_key` | 代码审查 `agent_vm.py`：`grep -n "os.environ" src/agent_vm.py` 应为空 |
| **C-9** | `DirectRunner.execute()` 必须传入净化后的 `env` dict，不继承全进程环境变量 | `test_direct_runner_env_sanitization()`：子进程内 `echo $OPENAI_API_KEY` 应为空 |

---

## 文件交付清单（新增）

| 文件 | 内容 | 交付阶段 |
|---|---|---|
| `src/agent_key_vault.py` | AgentKeyVault 密钥隔离 | Task #5 (AgentVM) |
| Agent/Account `secrets.json` | 密钥存储文件 | 部署配置 |
| `config/policy-default.jsonl` | 追加环境变量泄露 deny 规则 | Task #4 (ToolRegistry) |
