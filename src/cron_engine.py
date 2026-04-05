from __future__ import annotations

import json
import logging
import os
import time
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel, Field

# Lazy imports to avoid circular dependencies in _execute_payload
# from src.agent_vm import create_agent_vm
# from src.ops_ledger import OpsLedger
# from src.agent_manager import AgentManager

logger = logging.getLogger("OpsSentry.CronEngine")

class Schedule(BaseModel):
    kind: str  # "in", "at", "every", "cron"
    inMs: Optional[int] = None
    at: Optional[Union[str, int]] = None
    everyMs: Optional[int] = None
    expr: Optional[str] = None
    tz: Optional[str] = "Asia/Shanghai"
    jitter: Optional[int] = 0  # 抖动量 (秒), Phase 8 #71

class Payload(BaseModel):
    kind: str  # "command", "tool", "agent"
    command: Optional[str] = None
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    message: Optional[str] = None

class CronJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    schedule: Schedule
    payload: Payload
    uid: str
    did: Optional[str] = None  # target agent did
    enabled: bool = True
    deleteAfterRun: bool = False
    priority: int = 10  # 优先级 (0-100, 越高越优先), Phase 8 #71
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))

class CronEngine:
    """
    CronEngine: 定时任务调度引擎 (Phase 3 #23).
    支持 in/at/every/cron 四种调度，持久化存储于 ~/.accio/cron/jobs.json，
    执行结果自动对接 OpsLedger。
    """
    def __init__(
        self, 
        accio_home: Path,
        ops_ledger: Any, # OpsLedger
        agent_manager: Any, # AgentManager
        max_concurrent_jobs: int = 50 # 最大并发巡检数 (Phase 8 #71)
    ) -> None:
        self.accio_home = accio_home
        self.ops_ledger = ops_ledger
        self.agent_manager = agent_manager
        self.max_concurrent_jobs = max_concurrent_jobs
        self.jobs_file = self.accio_home / "cron/jobs.json"
        self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.scheduler = AsyncIOScheduler()
        self.semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self.active_jobs_count = 0
        self.jobs: Dict[str, CronJob] = {}
        self._load_jobs()

    def _load_jobs(self):
        if self.jobs_file.exists():
            try:
                with open(self.jobs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for job_dict in data:
                        job = CronJob(**job_dict)
                        self.jobs[job.id] = job
            except Exception as e:
                logger.error(f"Failed to load cron jobs: {e}")

    def _save_jobs(self):
        try:
            with open(self.jobs_file, "w", encoding="utf-8") as f:
                json_body = [j.model_dump() for j in self.jobs.values()]
                json.dump(json_body, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save cron jobs: {e}")

    async def start(self):
        """启动调度器并加载所有已启用的任务"""
        for job in self.jobs.values():
            if job.enabled:
                self._schedule_job(job)
        self.scheduler.start()
        logger.info("CronEngine started")

    async def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("CronEngine stopped")

    def _schedule_job(self, job: CronJob):
        trigger = None
        jitter = job.schedule.jitter or 0
        
        if job.schedule.kind == "in":
            run_date = datetime.now() + timedelta(milliseconds=job.schedule.inMs or 0)
            trigger = DateTrigger(run_date=run_date)
        elif job.schedule.kind == "at":
            if isinstance(job.schedule.at, int):
                run_date = datetime.fromtimestamp(job.schedule.at / 1000)
            else:
                run_date = datetime.fromisoformat(job.schedule.at)
            trigger = DateTrigger(run_date=run_date)
        elif job.schedule.kind == "every":
            trigger = IntervalTrigger(seconds=(job.schedule.everyMs or 0) / 1000, jitter=jitter)
        elif job.schedule.kind == "cron":
            # APScheduler 3.x cron trigger parsing
            parts = job.schedule.expr.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    timezone=job.schedule.tz,
                    jitter=jitter
                )
            elif len(parts) == 6:
                trigger = CronTrigger(
                    second=parts[0],
                    minute=parts[1],
                    hour=parts[2],
                    day=parts[3],
                    month=parts[4],
                    day_of_week=parts[5],
                    timezone=job.schedule.tz,
                    jitter=jitter
                )
        
        if trigger:
            self.scheduler.add_job(
                self._execute_job_wrapper,
                trigger=trigger,
                args=[job.id],
                id=job.id,
                replace_existing=True,
                max_instances=1 # 确保单个任务不会由于延迟导致并发重叠
            )

    async def add_job(self, job: CronJob) -> CronJob:
        """添加并持久化新任务"""
        self.jobs[job.id] = job
        if job.enabled:
            self._schedule_job(job)
        self._save_jobs()
        return job

    async def remove_job(self, job_id: str):
        """删除任务"""
        if job_id in self.jobs:
            del self.jobs[job_id]
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            self._save_jobs()

    async def _execute_job_wrapper(self, job_id: str):
        """调度执行包装器，负责日志记录与状态转换 (Phase 8 #71 增强)"""
        job = self.jobs.get(job_id)
        if not job or not job.enabled:
            return

        # Phase 8 #71: 动态反压与优先级丢弃
        # 如果当前并发已满且优先级较低 (低于 30)，则丢弃任务以保护集群
        if self.semaphore.locked() and job.priority < 30:
            logger.warning(f"Backpressure! Dropping low-priority task: {job.name} (pri={job.priority})")
            # 记录 OpsLedger 为跳过状态
            ledger_entry = self.ops_ledger.create_entry(
                action="cron_job_skipped",
                metadata={"job_id": job.id, "job_name": job.name, "reason": "Backpressure"}
            )
            # OpsLedger 强制状态流转: pending -> running -> completed
            self.ops_ledger.mark_running(ledger_entry.id)
            self.ops_ledger.mark_completed(ledger_entry.id, checkpoint={"status": "skipped"})
            return

        async with self.semaphore:
            logger.info(f"Executing cron job: {job.name} ({job.id})")
            
            # 记录 OpsLedger
            ledger_entry = self.ops_ledger.create_entry(
                action="cron_job_exec",
                metadata={"job_id": job.id, "job_name": job.name, "payload_kind": job.payload.kind}
            )
            self.ops_ledger.mark_running(ledger_entry.id)

            try:
                result = await self._execute_payload(job)
                self.ops_ledger.mark_completed(ledger_entry.id, checkpoint={"result": result})
            except Exception as e:
                logger.error(f"Cron job {job.id} failed: {str(e)}")
                self.ops_ledger.mark_failed(ledger_entry.id, error=str(e))

            if job.deleteAfterRun:
                await self.remove_job(job.id)

    async def _execute_payload(self, job: CronJob) -> Any:
        """根据 Payload 类型分发执行"""
        from src.dependencies import get_sandbox_provider
        from src.tool_registry import ToolRegistry
        
        if job.payload.kind == "command":
            enabled_groups = None
            if job.did:
                try:
                    profile = self.agent_manager.get_agent(job.uid, job.did)
                    enabled_groups = profile.tools
                except:
                    pass
            
            registry = ToolRegistry(
                ops_ledger=self.ops_ledger,
                sandbox=get_sandbox_provider(),
                enabled_groups=enabled_groups
            )
            return await registry.dispatch("bash", {"command": job.payload.command})

        elif job.payload.kind == "tool":
            enabled_groups = None
            if job.did:
                try:
                    profile = self.agent_manager.get_agent(job.uid, job.did)
                    enabled_groups = profile.tools
                except:
                    pass

            registry = ToolRegistry(
                ops_ledger=self.ops_ledger,
                sandbox=get_sandbox_provider(),
                enabled_groups=enabled_groups
            )
            return await registry.dispatch(job.payload.tool, job.payload.args or {})

        elif job.payload.kind == "agent":
            if not job.did:
                raise ValueError("Payload kind 'agent' requires a target agent 'did'")
            
            from src.agent_vm import create_agent_vm
            vm = create_agent_vm(job.uid, job.did)
            
            history = [{"role": "user", "content": job.payload.message}]
            final_result = []
            async for chunk in vm.chat(history):
                if chunk["type"] == "message":
                    final_result.append(chunk["message"])
            
            return final_result
        
        return None
