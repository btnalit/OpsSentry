from fastapi import Header, HTTPException
from src.agent_manager import AgentManager
from src.ops_ledger import OpsLedger
from src.sandbox import SandboxProvider, create_sandbox_provider
from src.skill_loader import SkillLoader
from src.cron_engine import CronEngine
from src.session_manager import SessionManager
from src.config_shield import ConfigShield
from src.global_sync import SyncBuffer
from src.agent_key_vault import AgentKeyVault
from src.message_router import MessageRouter
from src.cluster.shipper import AuditShipper
from src.cluster.heartbeat import HeartbeatSender
from src.cluster.alert_engine import AlertAggregator
from src.channels.feishu import FeishuChannel
from src.channels.dingtalk import DingTalkChannel
from src.auth import get_current_user
from pathlib import Path
import os
import redis

# Default home to current directory if not set
ACCIO_HOME = Path(os.environ.get("ACCIO_HOME", os.getcwd()))

_manager = None
_ledger = None
_sandbox = None
_skill_loader = None
_cron_engine = None
_session_manager = None
_config_shield = None
_sync_buffer = None
_key_vault = None
_message_router = None
_audit_shipper = None
_hb_sender = None
_alert_aggregator = None

def get_agent_manager() -> AgentManager:
    global _manager
    if _manager is None:
        redis_url = os.environ.get("REDIS_URL")
        _manager = AgentManager(accio_home=ACCIO_HOME, redis_url=redis_url)
    return _manager

def get_ops_ledger() -> OpsLedger:
    global _ledger
    if _ledger is None:
        # Use relative path to workdir for default ledger if not absolute
        ledger_path = ACCIO_HOME / "data/ops-queue/ledger.jsonl"
        _ledger = OpsLedger(ledger_path=ledger_path)
    return _ledger

def get_sandbox_provider() -> SandboxProvider:
    global _sandbox
    if _sandbox is None:
        _sandbox = create_sandbox_provider()
    return _sandbox

def get_skill_loader() -> SkillLoader:
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader(accio_home=ACCIO_HOME)
    return _skill_loader

def get_cron_engine() -> CronEngine:
    global _cron_engine
    if _cron_engine is None:
        max_concurrent = int(os.environ.get("MAX_CRON_CONCURRENCY", 10))
        _cron_engine = CronEngine(
            accio_home=ACCIO_HOME,
            ops_ledger=get_ops_ledger(),
            agent_manager=get_agent_manager(),
            max_concurrent_jobs=max_concurrent
        )
    return _cron_engine

def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(accio_home=ACCIO_HOME)
    return _session_manager

def get_config_shield() -> ConfigShield:
    global _config_shield
    if _config_shield is None:
        node_id = os.environ.get("OPSSENTRY_NODE_ID", "default-node")
        redis_url = os.environ.get("REDIS_URL")
        _config_shield = ConfigShield(
            node_id=node_id, 
            lock_dir=ACCIO_HOME / "data/locks",
            key_vault=get_key_vault(),
            redis_url=redis_url
        )
    return _config_shield

def get_sync_buffer() -> SyncBuffer:
    global _sync_buffer
    if _sync_buffer is None:
        _sync_buffer = SyncBuffer(
            shield=get_config_shield(),
            buffer_path=ACCIO_HOME / "data/ops-queue/sync-buffer.jsonl"
        )
    return _sync_buffer

def get_key_vault() -> AgentKeyVault:
    global _key_vault
    if _key_vault is None:
        _key_vault = AgentKeyVault(accio_home=ACCIO_HOME)
    return _key_vault

def get_message_router() -> MessageRouter:
    global _message_router
    if _message_router is None:
        _message_router = MessageRouter(
            manager=get_agent_manager(),
            ledger=get_ops_ledger()
        )
    return _message_router

def get_audit_shipper() -> AuditShipper | None:
    global _audit_shipper
    if _audit_shipper is None:
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            return None
        node_id = os.environ.get("OPSSENTRY_NODE_ID", "default-node")
        _audit_shipper = AuditShipper(
            node_id=node_id,
            redis_url=redis_url,
            ledger=get_ops_ledger()
        )
    return _audit_shipper

def get_heartbeat_sender() -> HeartbeatSender | None:
    global _hb_sender
    if _hb_sender is None:
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            return None
        node_id = os.environ.get("OPSSENTRY_NODE_ID", "default-node")
        secret = os.environ.get("CLUSTER_SECRET", "opssentry-default-secret")
        _hb_sender = HeartbeatSender(
            node_id=node_id,
            redis_url=redis_url,
            secret=secret,
            cron_engine=get_cron_engine()
        )
    return _hb_sender

def get_alert_aggregator() -> AlertAggregator:
    global _alert_aggregator
    if _alert_aggregator is None:
        redis_url = os.environ.get("REDIS_URL")
        # Initialize default channels (can be expanded later)
        shield = get_config_shield()
        # Default UID/DID for global alerts (placeholder)
        uid = os.environ.get("OPSSENTRY_ADMIN_UID", "admin")
        did = os.environ.get("OPSSENTRY_ADMIN_DID", "DID-ADMIN-CONSOLE")
        
        channels = []
        if os.environ.get("FEISHU_WEBHOOK_URL"):
            channels.append(FeishuChannel(shield, uid, did))
        if os.environ.get("DINGTALK_WEBHOOK_URL"):
            channels.append(DingTalkChannel(shield, uid, did))

        _alert_aggregator = AlertAggregator(
            redis_url=redis_url,
            channels=channels
        )
    return _alert_aggregator

def verify_user_id(uid: str, x_user_id: str = Header(...)) -> str:
    """IDOR 防护校验：确保请求中的 uid 与 X-User-ID 请求头匹配 (SDD §4.1)"""
    if uid != x_user_id:
        raise HTTPException(status_code=403, detail="Access denied: UID mismatch")
    return uid
