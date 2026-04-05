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
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return None

    @staticmethod
    def _build_key_set(did: str, provider: str, config: dict[str, Any]) -> AgentKeySet:
        if isinstance(config, str):
            # 兼容简写格式 "openai": "sk-..."
            return AgentKeySet(agent_did=did, provider=provider, api_key=config)
            
        return AgentKeySet(
            agent_did=did,
            provider=provider,
            api_key=config["api_key"],
            api_base=config.get("api_base"),
            extra={k: v for k, v in config.items() if k not in ("api_key", "api_base")},
        )
