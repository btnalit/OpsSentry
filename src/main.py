from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import logging
import os
from src.routers import agents, ledger, cron, sessions, system, skills, webhooks, cluster

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OpsSentry")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start CronEngine, AuditShipper, & HeartbeatSender
    from src.dependencies import get_cron_engine, get_audit_shipper, get_heartbeat_sender
    try:
        engine = get_cron_engine()
        await engine.start()
        logger.info("CronEngine lifecycle: STARTED")
    except Exception as e:
        logger.error(f"Failed to start CronEngine: {e}")
        
    try:
        shipper = get_audit_shipper()
        if shipper:
            shipper.start()
            logger.info("AuditShipper lifecycle: STARTED")
    except Exception as e:
        logger.error(f"Failed to start AuditShipper: {e}")

    try:
        hb_sender = get_heartbeat_sender()
        if hb_sender:
            hb_sender.start()
            logger.info("HeartbeatSender lifecycle: STARTED")
    except Exception as e:
        logger.error(f"Failed to start HeartbeatSender: {e}")

    # WebSocket 集群事件订阅
    from src.routers.sessions import manager_ws
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        manager_ws.start_redis_subscriber(redis_url)
    
    # Start AlertAggregator
    from src.dependencies import get_alert_aggregator
    try:
        aggregator = get_alert_aggregator()
        await aggregator.start()
        logger.info("AlertAggregator lifecycle: STARTED")
    except Exception as e:
        logger.error(f"Failed to start AlertAggregator: {e}")

    yield
    
    # Shutdown: Stop Services
    try:
        aggregator = get_alert_aggregator()
        await aggregator.stop()
        logger.info("AlertAggregator lifecycle: STOPPED")
    except Exception as e:
        logger.error(f"Failed to stop AlertAggregator: {e}")
    try:
        engine = get_cron_engine()
        await engine.stop()
        logger.info("CronEngine lifecycle: STOPPED")
    except Exception as e:
        logger.error(f"Failed to stop CronEngine: {e}")

    try:
        shipper = get_audit_shipper()
        if shipper:
            shipper.stop()
            logger.info("AuditShipper lifecycle: STOPPED")
    except Exception as e:
        logger.error(f"Failed to stop AuditShipper: {e}")

    try:
        hb_sender = get_heartbeat_sender()
        if hb_sender:
            hb_sender.stop()
            logger.info("HeartbeatSender lifecycle: STOPPED")
    except Exception as e:
        logger.error(f"Failed to stop HeartbeatSender: {e}")

app = FastAPI(
    title="OpsSentry API",
    description="Backend API for OpsSentry AI Agent Management & Operations Ledger",
    version="v1.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(agents.router, prefix="/api")
app.include_router(ledger.router, prefix="/api")
app.include_router(cron.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(cluster.router, prefix="/api")
app.include_router(system.router, prefix="/api")

@app.get("/")
async def root():
    return {
        "message": "OpsSentry API is running.",
        "version": "v1.0",
        "endpoints": ["/api/agents", "/api/ops/ledger", "/api/cron/jobs", "/api/sessions/chat", "/api/system/health"]
    }

# Remove redundant placeholder if sessions.router already handles it

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
