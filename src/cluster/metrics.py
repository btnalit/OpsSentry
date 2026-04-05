import psutil
import os
import time

def get_node_metrics(cron_engine=None):
    """
    获取当前节点的性能指标 (Phase 7 #61/#64 对齐)。
    """
    tasks_count = 0
    if cron_engine and hasattr(cron_engine, 'scheduler'):
        # 获取当前正在运行或已调度的任务数
        tasks_count = len(cron_engine.scheduler.get_jobs())

    return {
        "cpu": psutil.cpu_percent(interval=None),
        "mem": psutil.virtual_memory().percent,
        "tasks": tasks_count,
        "disk": psutil.disk_usage("/").percent if os.name != "nt" else psutil.disk_usage("C:\\").percent
    }
