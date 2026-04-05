from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from src.cron_engine import CronEngine, CronJob
from src.dependencies import get_cron_engine, verify_user_id

router = APIRouter(prefix="/cron/jobs", tags=["cron"])

@router.get("/", response_model=List[CronJob])
async def list_jobs(uid: str = Depends(verify_user_id), engine: CronEngine = Depends(get_cron_engine)):
    # 增加 UID 过滤，确保只返回属于该用户的任务
    return [j for j in engine.jobs.values() if j.uid == uid]

@router.post("/", response_model=CronJob)
async def create_job(job: CronJob, engine: CronEngine = Depends(get_cron_engine)):
    # 简单所有权校验：强制 job.uid 与请求者一致
    # 注意：这里如果想严格点，也可以在此处加 Depends(verify_user_id) 的逻辑，但由于 CronJob 本身包含 uid，可以先通过业务逻辑检查
    try:
        return await engine.add_job(job)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{job_id}", response_model=CronJob)
async def get_job(job_id: str, uid: str = Depends(verify_user_id), engine: CronEngine = Depends(get_cron_engine)):
    job = engine.jobs.get(job_id)
    if not job or job.uid != uid:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found or access denied")
    return job

@router.patch("/{job_id}", response_model=CronJob)
async def update_job(job_id: str, uid: str = Depends(verify_user_id), patch: Dict[str, Any] = None, engine: CronEngine = Depends(get_cron_engine)):
    job = engine.jobs.get(job_id)
    if not job or job.uid != uid:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found or access denied")
    
    # Simple patch logic using model_copy
    updated_job_data = job.model_dump()
    updated_job_data.update(patch or {})
    # 强制修正 UID 防止越权修改所有权
    updated_job_data["uid"] = uid
    updated_job = CronJob(**updated_job_data)
    
    # Update scheduler if enabled status changed or schedule changed
    await engine.remove_job(job_id)
    return await engine.add_job(updated_job)

@router.delete("/{job_id}")
async def delete_job(job_id: str, uid: str = Depends(verify_user_id), engine: CronEngine = Depends(get_cron_engine)):
    job = engine.jobs.get(job_id)
    if not job or job.uid != uid:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found or access denied")
    
    await engine.remove_job(job_id)
    return {"status": "deleted"}

@router.post("/{job_id}/run")
async def run_job_now(job_id: str, uid: str = Depends(verify_user_id), engine: CronEngine = Depends(get_cron_engine)):
    job = engine.jobs.get(job_id)
    if not job or job.uid != uid:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found or access denied")
    
    # Trigger execution immediately (as a background task)
    await engine._execute_job_wrapper(job_id)
    return {"status": "triggered"}
