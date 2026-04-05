# Phase 7: Distributed Dashboard & Cluster Monitoring Spec (#64)

## 1. 目标 (Objectives)
在赛博终端 HUD (React/Vite) 上实现对 OpsSentry 全集群节点状态、负载分布及故障转移过程的可视化监控。
通过集成后端集群 API，使董事长能实时感知“巡检军团”的健康度。

## 2. 监控架构 (Monitoring Architecture)

### 2.1 数据流向 (Data Flow)
```mermaid
graph LR
    A[Sentry Node 1] -- HB (Metrics) --> B((Redis))
    C[Sentry Node 2] -- HB (Metrics) --> B
    B -- Fetch Cluster State --> D[API Layer (FastAPI)]
    D -- WebSocket/REST --> E[Frontend HUD]
    E -- Visualization --> F[User Dashboard]
```

### 2.2 数据源 (Data Sources)
*   **节点元数据**: 从 `sentry:cluster:nodes` (Hash) 获取。
*   **节点实时负载**: 从 `sentry:node:hb:{node_id}` (JSON Payload) 解析。
*   **Leader 身份**: 检查 `sentry:leader:lease` 的持有者。
*   **任务分布**: 汇总 `sentry:task:registry` (Hash)。

## 3. 前端可视化组件 (UI Components)

### 3.1 集群热力图 (Cluster Heatmap)
*   **展示**: 以格子形式展示所有 ACTIVE/SUSPECT/DEAD 节点。
*   **指标**: 格子颜色深浅代表 CPU/内存负载。
*   **交互**: 点击节点查看详细的 `AgentVM` 运行日志和任务列表。

### 3.2 故障告警脉冲 (Failover Pulse)
*   **展示**: 当节点状态变为 `SUSPECT` 或 `DEAD` 时，仪表盘顶部出现红色警报。
*   **动态**: 实时动画展示任务从死亡节点“漂移”到接管节点的过程。

### 3.3 审计流聚合视图 (Aggregated Ledger)
*   **展示**: 全局审计流列表，增加 `source_node` 标签，区分不同节点的执行记录。

## 4. 后端 API 定义 (API Spec)

### 4.1 `GET /api/v1/cluster/status`
返回全集群快照。
```json
{
  "leader_id": "sentry-master-01",
  "nodes": [
    {
      "id": "worker-01",
      "status": "ACTIVE",
      "last_seen": 1712217600000,
      "metrics": { "cpu": 15.2, "mem": 480, "tasks": 2 }
    }
  ],
  "global_metrics": {
    "total_nodes": 12,
    "active_tasks": 45,
    "redis_healthy": true
  }
}
```

### 4.2 `WS /api/v1/cluster/stream`
通过 WebSocket 实时推送心跳变更与 Failover 事件。

## 5. 任务分工
*   **Frontend Master**: 实现 React 仪表盘中的集群节点列表组件与 Failover 动画。
*   **Developer**: 在 `src/main.py` 中实现 `/cluster/status` 接口，并对接 Redis 集群数据。
*   **Architect (Myself)**: 确保前端可视化逻辑与 #61 故障转移状态机严格对齐。
