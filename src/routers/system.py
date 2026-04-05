import os
import time
from fastapi import APIRouter, Depends
from src.dependencies import get_cron_engine, ACCIO_HOME
from src.auth import get_current_user

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/health")
async def health_check(engine = Depends(get_cron_engine), user = Depends(get_current_user)):
    """
    深度健康检查接口 (QA 建议 #34)。
    检查 API 状态、CronEngine 运行状态及存储 I/O。
    受 JWT 鉴权保护 (Phase 8 #70.3 测试点)。
    """
    health_status = {
        "status": "ok",
        "timestamp": int(time.time()),
        "checks": {
            "api": "alive",
            "cron_engine": "running" if engine.scheduler.running else "stopped",
            "storage_io": "ok"
        }
    }
    
    # 检查存储 I/O 权限
    try:
        test_file = ACCIO_HOME / "data/.io_test"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["checks"]["storage_io"] = f"error: {str(e)}"
        
    return health_status
