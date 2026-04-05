import asyncio
import httpx
import logging
from pathlib import Path
import os
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HealthCheck")

BASE_URL = "http://localhost:8000"

async def check_api_health():
    """探测 API 存活状态及核心元数据"""
    async with httpx.AsyncClient() as client:
        try:
            # 1. 探测根接口
            resp = await client.get(f"{BASE_URL}/")
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[PASS] API Root is alive. Version: {data.get('version')}")
                return True
            else:
                logger.error(f"[FAIL] API Root returned status {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"[CRITICAL] API Connection Failed: {e}")
            return False

async def check_cron_persistence():
    """检查 Cron 任务持久化文件状态"""
    accio_home = Path(os.environ.get("ACCIO_HOME", os.getcwd()))
    jobs_path = accio_home / ".accio/cron/jobs.json"
    if jobs_path.exists():
        size = jobs_path.stat().st_size
        logger.info(f"[PASS] Cron persistence file exists. Size: {size} bytes")
        return True
    else:
        logger.warn(f"[WARN] Cron persistence file missing at {jobs_path}")
        return False

async def run_diagnostic():
    """模拟 15 分钟深度唤醒后的自检逻辑"""
    logger.info("=== Starting OpsSentry Resilience Diagnostic ===")
    api_ok = await check_api_health()
    cron_ok = await check_cron_persistence()
    
    if api_ok and cron_ok:
        logger.info("=== Result: SYSTEM HEALTHY ===")
    else:
        logger.error("=== Result: SYSTEM UNHEALTHY - Manual Intervention Required ===")

if __name__ == "__main__":
    # In a real environment, this would be triggered by cron or a background worker
    asyncio.run(run_diagnostic())
