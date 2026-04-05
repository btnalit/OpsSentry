import asyncio
import os
import pytest
from datetime import datetime, timedelta
from src.cron_engine import CronEngine, CronJob, Schedule, Payload
from src.ops_ledger import OpsLedger
from src.agent_manager import AgentManager
from pathlib import Path

@pytest.fixture
def test_env(tmp_path):
    accio_home = tmp_path
    (accio_home / "data/cron").mkdir(parents=True)
    (accio_home / "data/ops-queue").mkdir(parents=True)
    
    ledger = OpsLedger(ledger_path=accio_home / "data/ops-queue/ledger.db")
    # AgentManager typically expects a real workspace, but we'll mock or use a dummy path
    manager = AgentManager(accio_home=accio_home)
    
    # Init CronEngine with small concurrency for easy testing
    engine = CronEngine(accio_home=accio_home, ops_ledger=ledger, agent_manager=manager, max_concurrent_jobs=2)
    return engine, ledger

@pytest.mark.asyncio
async def test_cron_storm_priority_drop(test_env):
    """验证在高并发下，低优先级任务被丢弃，高优先级任务进入队列"""
    engine, ledger = test_env
    
    # 我们构造一个长耗时的 Payload 模拟 (虽然目前 _execute_payload 是异步的，
    # 但我们可以通过 mock 或者让它调用一个耗时的命令)
    
    # 注入一个耗时的任务占满 semaphore (并发=2)
    job_heavy1 = CronJob(
        id="heavy1", name="Heavy 1", uid="user1",
        schedule=Schedule(kind="in", inMs=10),
        payload=Payload(kind="command", command="python -c 'import time; time.sleep(1)'"),
        priority=100
    )
    job_heavy2 = CronJob(
        id="heavy2", name="Heavy 2", uid="user1",
        schedule=Schedule(kind="in", inMs=10),
        payload=Payload(kind="command", command="python -c 'import time; time.sleep(1)'"),
        priority=100
    )
    
    await engine.add_job(job_heavy1)
    await engine.add_job(job_heavy2)
    
    # 启动引擎并等待任务开始
    await engine.start()
    await asyncio.sleep(0.5) # 给一点时间让任务启动并占满 semaphore
    
    # 此时并发已满。尝试加入一个低优先级任务和一个高优先级任务
    job_low = CronJob(
        id="low_pri", name="Low Priority", uid="user1",
        schedule=Schedule(kind="in", inMs=0),
        payload=Payload(kind="command", command="python -c 'print(\"low\")'"),
        priority=10  # < 30, 应该被丢弃
    )
    job_high = CronJob(
        id="high_pri", name="High Priority", uid="user1",
        schedule=Schedule(kind="in", inMs=0),
        payload=Payload(kind="command", command="python -c 'print(\"high\")'"),
        priority=90  # > 30, 应该排队等待 acquire
    )
    
    # 手动触发执行包装器 (模拟调度器触发)
    task_low = asyncio.create_task(engine._execute_job_wrapper("low_pri"))
    engine.jobs["low_pri"] = job_low # 确保引擎能查到
    
    task_high = asyncio.create_task(engine._execute_job_wrapper("high_pri"))
    engine.jobs["high_pri"] = job_high
    
    await asyncio.gather(task_low, task_high)
    
    # 检查审计日志
    # 使用 sqlite 查询 ledger.db (OpsLedger 现在使用 SQLite)
    import sqlite3
    conn = sqlite3.connect(ledger.ledger_path)
    cursor = conn.cursor()
    
    # 查丢弃的任务
    cursor.execute("SELECT action, checkpoint FROM ledger WHERE metadata LIKE '%low_pri%'")
    rows = cursor.fetchall()
    assert any(row[0] == "cron_job_skipped" for row in rows)
    
    # 查执行的任务
    cursor.execute("SELECT action FROM ledger WHERE metadata LIKE '%high_pri%'")
    rows = cursor.fetchall()
    assert any(row[0] == "cron_job_exec" for row in rows)
    
    await engine.stop()
    conn.close()

@pytest.mark.asyncio
async def test_cron_jitter_config(test_env):
    """验证 Jitter 配置是否正确传递给 APScheduler"""
    engine, _ = test_env
    job = CronJob(
        id="jitter_test", name="Jitter Test", uid="user1",
        schedule=Schedule(kind="every", everyMs=1000, jitter=500),
        payload=Payload(kind="command", command="echo 1")
    )
    
    await engine.add_job(job)
    await engine.start()
    aps_job = engine.scheduler.get_job("jitter_test")
    
    # 检查 APScheduler 的 trigger 是否带有 jitter
    assert hasattr(aps_job.trigger, "jitter")
    assert aps_job.trigger.jitter == 500
    
    await engine.stop()
