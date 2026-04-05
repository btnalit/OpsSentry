from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
import threading
import time
import hmac
import hashlib
import logging
from typing import Any, Mapping, Optional
import uuid

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger("OpsSentry.AgentManager")

DEFAULT_ACCIO_HOME = Path.home() / ".accio"
CORE_FILE_NAMES = ("SOUL.md", "IDENTITY.md", "AGENTS.md", "MEMORY.md", "USER.md")
TOOL_REGISTRY_FILE = "tool-registry.jsonc"
AGENT_CONFIG_FILE = "agent_config.json"
SKILLS_DIR_NAME = "skills"
VALID_VIBES = {"professional", "expert", "balance"}
VALID_MODEL_PROVIDERS = {"claude", "openai", "qwen", "moonshot", "zhipu", "minimax", "auto"}
DEFAULT_TOOL_GROUPS = {
    "file_system": ["list", "read", "grep", "glob", "ripgrep", "write", "edit"],
    "command_execution": ["bash", "process"],
    "network_probe": ["web_fetch"],
    "cron_trigger": ["cron"],
    "human_confirm": ["question"],
    "memory_planning": ["memory_search", "memory_get", "task_create", "task_get", "task_update", "task_list"],
    "agent_collaboration": ["sessions_spawn", "sessions_list", "sessions_history", "sessions_send"],
    "external_integration": ["mcp_call"],
    "notification": ["listen_gmail_reply", "unlisten_gmail"],
}
DEFAULT_TOOL_ENABLEMENT = {
    "file_system": True,
    "command_execution": True,
    "network_probe": True,
    "cron_trigger": True,
    "human_confirm": False,
    "memory_planning": True,
    "agent_collaboration": True,
    "external_integration": True,
    "notification": True,
}
DEFAULT_DENIED_TOOLS = [
    "product_supplier_search",
    "image_generate",
    "image_edit",
    "see_image",
    "web_search",
    "get_weather",
    "get_location",
]


class AgentManagerError(RuntimeError):
    pass


class AgentNotFoundError(AgentManagerError):
    pass


class AgentAlreadyExistsError(AgentManagerError):
    pass


class InvalidAgentConfigError(AgentManagerError):
    pass


class InvalidCoreFileError(AgentManagerError):
    pass


class InvalidToolRegistryError(AgentManagerError):
    pass


class InvalidSkillBindingError(AgentManagerError):
    pass


def utc_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class AgentCreateRequest:
    uid: str
    name: str
    description: str
    vibe: str
    model_provider: str
    model_id: str
    tools: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_TOOL_ENABLEMENT))
    skills: list[str] = field(default_factory=list)
    core_files: dict[str, str] = field(default_factory=dict)
    did: str | None = None

    def __post_init__(self) -> None:
        self.uid = _require_non_empty(self.uid, field_name="uid")
        self.name = _require_non_empty(self.name, field_name="name")
        self.description = _require_non_empty(self.description, field_name="description")
        self.vibe = _validate_vibe(self.vibe)
        self.model_provider = _validate_model_provider(self.model_provider)
        self.model_id = _require_non_empty(self.model_id, field_name="model_id")
        self.tools = _normalize_tools(self.tools)
        self.skills = _normalize_skills(self.skills)
        self.core_files = _normalize_core_file_overrides(self.core_files)
        if self.did is not None:
            self.did = _normalize_did(self.did)


@dataclass(slots=True)
class AgentProfile:
    did: str
    uid: str
    name: str
    description: str
    vibe: str
    model_provider: str
    model_id: str
    tools: dict[str, bool]
    skills: list[str]
    created_at: int
    updated_at: int

    @classmethod
    def from_record(cls, uid: str, record: Mapping[str, Any]) -> "AgentProfile":
        return cls(
            did=_normalize_did(record["did"]),
            uid=_require_non_empty(uid, field_name="uid"),
            name=_require_non_empty(record["name"], field_name="name"),
            description=_require_non_empty(record["description"], field_name="description"),
            vibe=_validate_vibe(record["vibe"]),
            model_provider=_validate_model_provider(record["model_provider"]),
            model_id=_require_non_empty(record["model_id"], field_name="model_id"),
            tools=_normalize_tools(record.get("tools") or DEFAULT_TOOL_ENABLEMENT),
            skills=_normalize_skills(record.get("skills") or []),
            created_at=int(record["created_at"]),
            updated_at=int(record["updated_at"]),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "did": self.did,
            "name": self.name,
            "description": self.description,
            "vibe": self.vibe,
            "model_provider": self.model_provider,
            "model_id": self.model_id,
            "tools": dict(self.tools),
            "skills": list(self.skills),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class AgentManager:
    def __init__(self, accio_home: str | Path = DEFAULT_ACCIO_HOME, redis_url: str | None = None) -> None:
        self.accio_home = Path(accio_home)
        self.accounts_dir = self.accio_home / "accounts"
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.redis_url = redis_url
        self._redis_client = None
        if redis_url:
            if redis is None:
                raise ImportError("redis-py is required for Cluster mode")
            self._redis_client = redis.from_url(redis_url, decode_responses=True)
            logger.info("AgentManager initialized with Cluster mode (Redis enabled)")

    def validate_heartbeat(self, payload: dict[str, Any], secret: str) -> bool:
        """
        Phase 7 #61.1: 校验心跳包签名 (HMAC-SHA256)。
        """
        provided_hmac = payload.get("hmac")
        if not provided_hmac:
            return False
            
        # 复制数据并移除 hmac 字段进行计算
        data = payload.copy()
        data.pop("hmac", None)
        message = json.dumps(data, sort_keys=True).encode("utf-8")
        expected_hmac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(provided_hmac, expected_hmac)

    def perform_failover(self, dead_node_id: str) -> int:
        """
        Phase 7 #61.1: 执行故障转移逻辑。
        清理已死亡节点的任务注册与分布式锁。
        """
        if not self._redis_client:
            logger.warning("Failover called but Redis client is not configured.")
            return 0

        logger.info(f"Initiating Failover for DEAD node: {dead_node_id}")
        
        # 1. 扫描任务注册表
        # sentry:task:registry (Hash) -> {task_id: node_id}
        try:
            all_tasks = self._redis_client.hgetall("sentry:task:registry")
            tasks_to_reclaim = [tid for tid, nid in all_tasks.items() if nid == dead_node_id]
            
            if not tasks_to_reclaim:
                logger.info(f"No tasks found for node {dead_node_id}. Failover complete.")
                return 0

            reclaimed_count = 0
            for tid in tasks_to_reclaim:
                # 2. 原子释放任务锁与清理注册
                # 使用 pipeline 保证逻辑完整性
                pipe = self._redis_client.pipeline()
                pipe.delete(f"sentry:task:lock:{tid}")
                pipe.hdel("sentry:task:registry", tid)
                
                # 3. 发布重平衡信号 (REBALANCE)
                pipe.publish("sentry:msg:broadcast", json.dumps({
                    "event": "REBALANCE",
                    "task_id": tid,
                    "old_node": dead_node_id,
                    "reason": "NODE_DEAD"
                }))
                pipe.execute()
                
                reclaimed_count += 1
                logger.info(f"Reclaimed task {tid} from {dead_node_id} and triggered rebalance.")

            # 4. Emit Alert (Phase 8 #72)
            try:
                from src.cluster.alert_engine import AlertEvent
                from src.dependencies import get_alert_aggregator
                import asyncio
                
                event = AlertEvent(
                    type="NODE_DEAD",
                    severity="CRITICAL",
                    source=dead_node_id,
                    message=f"Node {dead_node_id} has been declared DEAD. Reclaiming {len(tasks_to_reclaim)} tasks.",
                    details={"tasks": tasks_to_reclaim}
                )
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(get_alert_aggregator().emit(event))
                except RuntimeError:
                    # Fallback for sync contexts
                    asyncio.run(get_alert_aggregator().emit(event))
            except Exception as ae:
                logger.error(f"Failed to emit failover alert: {ae}")

            return reclaimed_count
        except Exception as e:
            logger.error(f"Failover failed for {dead_node_id}: {e}")
            return 0

    def create_agent(self, config: AgentCreateRequest) -> AgentProfile:
        with self._lock:
            did = config.did or self._generate_did()
            uid = config.uid
            core_dir = self._agent_core_dir(uid, did)
            if core_dir.exists():
                raise AgentAlreadyExistsError(f"agent already exists: {did}")

            core_dir.mkdir(parents=True, exist_ok=False)
            (core_dir / SKILLS_DIR_NAME).mkdir(parents=True, exist_ok=True)

            now = utc_ms()
            profile = AgentProfile(
                did=did,
                uid=uid,
                name=config.name,
                description=config.description,
                vibe=config.vibe,
                model_provider=config.model_provider,
                model_id=config.model_id,
                tools=dict(config.tools),
                skills=list(config.skills),
                created_at=now,
                updated_at=now,
            )

            self._write_json(core_dir / AGENT_CONFIG_FILE, profile.to_record())
            self._write_json(core_dir / TOOL_REGISTRY_FILE, self._build_tool_registry(profile.tools))
            for filename, content in self._default_core_files(profile, overrides=config.core_files).items():
                self._write_text(core_dir / filename, content)
            return self.get_agent(uid, profile.did)

    def get_agent(self, uid: str, did: str) -> AgentProfile:
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            return self._load_profile(core_dir)

    def update_agent(self, uid: str, did: str, patch: Mapping[str, Any]) -> AgentProfile:
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            profile = self._load_profile(core_dir)
            allowed_fields = {"name", "description", "vibe", "model_provider", "model_id", "tools", "skills"}
            unknown_fields = set(patch) - allowed_fields
            if unknown_fields:
                raise InvalidAgentConfigError(f"unsupported patch fields: {sorted(unknown_fields)}")

            if "name" in patch:
                profile.name = _require_non_empty(patch["name"], field_name="name")
            if "description" in patch:
                profile.description = _require_non_empty(patch["description"], field_name="description")
            if "vibe" in patch:
                profile.vibe = _validate_vibe(patch["vibe"])
            if "model_provider" in patch:
                profile.model_provider = _validate_model_provider(patch["model_provider"])
            if "model_id" in patch:
                profile.model_id = _require_non_empty(patch["model_id"], field_name="model_id")
            if "tools" in patch:
                profile.tools = _normalize_tools(patch["tools"])
                self._write_json(core_dir / TOOL_REGISTRY_FILE, self._build_tool_registry(profile.tools))
            if "skills" in patch:
                profile.skills = _normalize_skills(patch["skills"])

            profile.updated_at = utc_ms()
            self._write_json(core_dir / AGENT_CONFIG_FILE, profile.to_record())
            return AgentProfile.from_record(profile.uid, profile.to_record())

    def delete_agent(self, uid: str, did: str) -> None:
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            agent_dir = core_dir.parent
            shutil.rmtree(agent_dir)

    def list_agents(self, uid: str) -> list[AgentProfile]:
        uid = _require_non_empty(uid, field_name="uid")
        with self._lock:
            agents_dir = self.accounts_dir / uid / "agents"
            if not agents_dir.exists():
                return []
            profiles: list[AgentProfile] = []
            for config_path in sorted(agents_dir.glob(f"*/agent-core/{AGENT_CONFIG_FILE}")):
                profiles.append(self._load_profile(config_path.parent))
            return sorted(profiles, key=lambda item: (item.created_at, item.did))

    def read_core_file(self, uid: str, did: str, filename: str) -> str:
        normalized_file = self._validate_core_filename(filename)
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            path = core_dir / normalized_file
            if not path.exists():
                raise InvalidCoreFileError(f"core file not found: {normalized_file}")
            return path.read_text(encoding="utf-8")

    def write_core_file(self, uid: str, did: str, filename: str, content: str) -> None:
        normalized_file = self._validate_core_filename(filename)
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            self._write_text(core_dir / normalized_file, str(content))

    def get_tool_registry(self, uid: str, did: str) -> dict[str, Any]:
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            path = core_dir / TOOL_REGISTRY_FILE
            if not path.exists():
                raise InvalidToolRegistryError(f"tool registry not found for agent: {did}")
            return self._read_json(path)

    def update_tool_registry(self, uid: str, did: str, tools: Mapping[str, bool]) -> None:
        normalized_tools = _normalize_tools(tools)
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            profile = self._load_profile(core_dir)
            profile.tools = dict(normalized_tools)
            profile.updated_at = utc_ms()
            self._write_json(core_dir / AGENT_CONFIG_FILE, profile.to_record())
            self._write_json(core_dir / TOOL_REGISTRY_FILE, self._build_tool_registry(profile.tools))

    def bind_skill(self, uid: str, did: str, skill_name: str) -> None:
        normalized_skill = _normalize_skill_name(skill_name)
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            profile = self._load_profile(core_dir)
            if normalized_skill not in profile.skills:
                profile.skills.append(normalized_skill)
                profile.updated_at = utc_ms()
                self._write_json(core_dir / AGENT_CONFIG_FILE, profile.to_record())

    def unbind_skill(self, uid: str, did: str, skill_name: str) -> None:
        normalized_skill = _normalize_skill_name(skill_name)
        with self._lock:
            core_dir = self._resolve_agent_core_dir(uid, did)
            profile = self._load_profile(core_dir)
            if normalized_skill in profile.skills:
                profile.skills = [skill for skill in profile.skills if skill != normalized_skill]
                profile.updated_at = utc_ms()
                self._write_json(core_dir / AGENT_CONFIG_FILE, profile.to_record())


    def _build_tool_registry(self, enabled_groups: Mapping[str, bool]) -> dict[str, Any]:
        return {
            "enabled_groups": dict(_normalize_tools(enabled_groups)),
            "tool_groups": dict(DEFAULT_TOOL_GROUPS),
            "denied_tools": list(DEFAULT_DENIED_TOOLS),
        }

    def _default_core_files(self, profile: AgentProfile, *, overrides: Mapping[str, str]) -> dict[str, str]:
        defaults = {
            "SOUL.md": (
                f"# {profile.name} SOUL\n\n"
                f"- 核心原则：证据优先，先诊断后执行。\n"
                f"- 安全边界：未经明确批准，不执行破坏性命令。\n"
                f"- 输出要求：结论简洁，记录关键操作与风险。\n"
            ),
            "IDENTITY.md": (
                f"# 身份定义\n\n"
                f"- 名称：{profile.name}\n"
                f"- 风格：{profile.vibe}\n"
                f"- 职责：{profile.description}\n"
                f"- 模型：{profile.model_provider}/{profile.model_id}\n"
            ),
            "AGENTS.md": (
                "# 协作规则\n\n"
                "- 高风险操作必须先给出风险说明。\n"
                "- 需要协作时，优先把任务拆成独立子任务。\n"
                "- 无法确认的信息必须显式标注不确定性。\n"
            ),
            "MEMORY.md": "# Long-term Memory\n\n",
            "USER.md": (
                "# User Profile\n\n"
                "- 服务对象：IT 运维团队\n"
                "- 默认时区：Asia/Shanghai\n"
                "- 目标：提升巡检、告警响应和变更审计效率\n"
            ),
        }
        materialized = dict(defaults)
        for filename, content in overrides.items():
            materialized[filename] = content
        return materialized

    def _load_profile(self, core_dir: Path) -> AgentProfile:
        uid = core_dir.parents[2].name
        record = self._read_json(core_dir / AGENT_CONFIG_FILE)
        return AgentProfile.from_record(uid, record)

    def _resolve_agent_core_dir(self, uid: str, did: str) -> Path:
        uid = _require_non_empty(uid, field_name="uid")
        normalized = _normalize_did(did)
        path = self.accounts_dir / uid / "agents" / normalized / "agent-core"
        if not path.exists():
            raise AgentNotFoundError(normalized)
        return path

    def _agent_core_dir(self, uid: str, did: str) -> Path:
        return self.accounts_dir / uid / "agents" / did / "agent-core"

    def _generate_did(self) -> str:
        token = uuid.uuid4().hex.upper()
        return f"DID-{token[:8]}-{token[8:14]}"

    def _validate_core_filename(self, filename: str) -> str:
        normalized = str(filename).strip()
        if normalized not in CORE_FILE_NAMES:
            raise InvalidCoreFileError(f"unsupported core file: {filename}")
        return normalized

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise AgentManagerError(f"missing json file: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonc":
            # 剥离单行注释（// ...），但不剥离 URL 中的 //
            text = re.sub(r'(?<!:)//.*?$', '', text, flags=re.MULTILINE)
        return json.loads(text)

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @classmethod
    def _write_json(cls, path: Path, payload: Mapping[str, Any]) -> None:
        header = ""
        if path.name == TOOL_REGISTRY_FILE:
            header = (
                "// OpsSentry tool-registry.jsonc\n"
                "// Auto-generated by AgentManager. Do not edit manually.\n"
                "// Tool group definitions: see SDD §3.3\n"
            )
        json_body = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
        cls._write_text(path, header + json_body + "\n")


def _require_non_empty(value: Any, *, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise InvalidAgentConfigError(f"{field_name} must not be empty")
    return text


def _validate_vibe(value: Any) -> str:
    vibe = _require_non_empty(value, field_name="vibe")
    if vibe not in VALID_VIBES:
        raise InvalidAgentConfigError(f"unsupported vibe: {vibe}")
    return vibe


def _validate_model_provider(value: Any) -> str:
    provider = _require_non_empty(value, field_name="model_provider")
    if provider not in VALID_MODEL_PROVIDERS:
        raise InvalidAgentConfigError(f"unsupported model_provider: {provider}")
    return provider


def _normalize_did(value: Any) -> str:
    did = _require_non_empty(value, field_name="did").upper()
    if not did.startswith("DID-"):
        raise InvalidAgentConfigError(f"invalid did format: {did}")
    if any(sep in did for sep in ("/", "\\")) or ".." in did:
        raise InvalidAgentConfigError(f"path traversal detected in did: {did}")
    return did


def _normalize_tools(value: Mapping[str, Any]) -> dict[str, bool]:
    normalized = dict(DEFAULT_TOOL_ENABLEMENT)
    for key, enabled in dict(value).items():
        if key not in DEFAULT_TOOL_GROUPS:
            raise InvalidToolRegistryError(f"unsupported tool group: {key}")
        normalized[key] = bool(enabled)
    return normalized


def _normalize_skills(skills: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    normalized: list[str] = []
    for skill in skills:
        cleaned = _normalize_skill_name(skill)
        if cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _normalize_skill_name(skill_name: Any) -> str:
    skill = str(skill_name).strip()
    if not skill:
        raise InvalidSkillBindingError("skill_name must not be empty")
    if any(sep in skill for sep in ("/", "\\")) or skill in {".", ".."}:
        raise InvalidSkillBindingError(f"invalid skill_name: {skill}")
    return skill


def _normalize_core_file_overrides(overrides: Mapping[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for filename, content in dict(overrides).items():
        if filename not in CORE_FILE_NAMES:
            raise InvalidCoreFileError(f"unsupported core file override: {filename}")
        normalized[filename] = str(content)
    return normalized
