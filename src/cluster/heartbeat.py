import hmac
import hashlib
import json
import time
import threading
import logging
from typing import Optional, Any
from src.cluster.metrics import get_node_metrics

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger("HeartbeatSender")

DEFAULT_HB_INTERVAL = 10.0  # 10s as per Spec #61
DEFAULT_HB_SECRET = "opssentry-default-secret"

class HeartbeatSender:
    """
    Phase 7 #61: 集群心跳发送器。
    周期性上报节点状态、负载指标，并附加 HMAC-SHA256 签名。
    """
    
    def __init__(
        self,
        node_id: str,
        redis_url: str,
        secret: str = DEFAULT_HB_SECRET,
        interval: float = DEFAULT_HB_INTERVAL,
        cron_engine: Optional[Any] = None,
    ) -> None:
        self.node_id = node_id
        self.redis_url = redis_url
        self.secret = secret
        self.interval = interval
        self.cron_engine = cron_engine
        
        if redis is None:
            raise ImportError("redis-py is required for HeartbeatSender")
            
        self._redis_client = redis.from_url(redis_url, decode_responses=True)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._hb_key = f"sentry:node:hb:{self.node_id}"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name=f"hb-{self.node_id}")
        self._thread.start()
        logger.info(f"HeartbeatSender started for node: {self.node_id}")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            logger.info("HeartbeatSender stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._send_heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat send failed: {e}")
            
            if self._stop_event.wait(self.interval):
                break

    def _send_heartbeat(self) -> None:
        now_ms = int(time.time() * 1000)
        payload = {
            "node_id": self.node_id,
            "ts": now_ms,
            "status": "ACTIVE",
            "metrics": get_node_metrics(self.cron_engine)
        }
        
        # Calculate HMAC-SHA256
        message = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(self.secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        payload["hmac"] = signature
        
        # Store in Redis (TTL = 45s, triple the HB to allow for some network jitter before SUSPECT/DEAD)
        self._redis_client.set(self._hb_key, json.dumps(payload), px=45000)
        
        # Also publish to broadcast channel if needed
        # self._redis_client.publish("sentry:msg:broadcast", json.dumps({"event": "HB", "node_id": self.node_id}))
        
        logger.debug(f"Heartbeat sent for {self.node_id}")
