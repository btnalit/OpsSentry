from fastapi import APIRouter, Depends, HTTPException
from typing import Any, List, Dict
import os
import json
import time
from src.dependencies import get_agent_manager

router = APIRouter(prefix="/cluster", tags=["Cluster"])

@router.get("/status")
async def get_cluster_status(manager=Depends(get_agent_manager)):
    """
    Phase 7 #64.1: 获取全集群状态快照。
    聚合来自 Redis 的节点心跳、负载与任务分布。
    """
    if not manager._redis_client:
        return {
            "leader_id": "standalone",
            "nodes": [
                {
                    "id": os.environ.get("OPSSENTRY_NODE_ID", "default-node"),
                    "status": "ACTIVE",
                    "last_seen": int(time.time() * 1000),
                    "metrics": {"cpu": 0, "mem": 0, "tasks": 0}
                }
            ],
            "global_metrics": {
                "total_nodes": 1,
                "active_tasks": 0,
                "redis_healthy": False
            }
        }

    try:
        redis = manager._redis_client
        # 1. Get Leader ID
        leader_lease = redis.get("sentry:leader:lease")
        
        # 2. Get All Nodes via Heartbeat Keys
        # Scan sentry:node:hb:*
        node_keys = redis.keys("sentry:node:hb:*")
        nodes = []
        total_tasks = 0
        
        now_ms = int(time.time() * 1000)
        
        for key in node_keys:
            node_id = key.split(":")[-1]
            raw_hb = redis.get(key)
            if not raw_hb:
                continue
                
            hb_data = json.loads(raw_hb)
            last_seen = hb_data.get("ts", 0)
            
            # Status Logic from #61
            # ACTIVE (<15s), SUSPECT (15-30s), DEAD (>30s)
            diff_sec = (now_ms - last_seen) / 1000.0
            status = "ACTIVE"
            if diff_sec > 30:
                status = "DEAD"
            elif diff_sec > 15:
                status = "SUSPECT"
                
            metrics = hb_data.get("metrics", {"cpu": 0, "mem": 0, "tasks": 0})
            total_tasks += metrics.get("tasks", 0)
            
            nodes.append({
                "id": node_id,
                "status": status,
                "last_seen": last_seen,
                "metrics": metrics
            })

        # 3. Aggregate Global Metrics
        return {
            "leader_id": leader_lease,
            "nodes": nodes,
            "global_metrics": {
                "total_nodes": len(nodes),
                "active_tasks": total_tasks,
                "redis_healthy": True
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cluster status fetch failed: {str(e)}")
