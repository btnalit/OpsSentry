# Phase 7: Heartbeat Protocol & Failover State Machine Spec (#61)

## 1. 目标 (Objectives)
定义 OpsSentry 分布式集群的心跳广播格式、频率以及节点状态变迁逻辑，实现自动化的故障感知与任务重分配（Failover）。

## 2. 心跳协议 (Heartbeat Protocol)

### 2.1 传输机制
*   **通道**: Redis Pub/Sub (`sentry:cluster:heartbeat`)
*   **频率**: 每 10 秒发送一次。
*   **租约**: 每个节点在 Redis 中持有 `sentry:node:hb:{node_id}` Key，TTL 为 15 秒。

### 2.2 数据格式 (JSON)
```json
{
  "version": "1.0",
  "node_id": "worker-01",
  "timestamp": 1712217600000,
  "status": "ACTIVE",
  "metrics": {
    "cpu": 12.5,
    "mem": 450,
    "tasks_active": 3
  },
  "hmac": "sha256_signature_of_payload"
}
```

## 3. 故障转移状态机 (Failover State Machine)

节点状态由集群 Leader 维护，变迁规则如下：

| 当前状态 | 触发事件 | 目标状态 | 动作 (Action) |
| :--- | :--- | :--- | :--- |
| **ACTIVE** | 15s 未收到心跳且租约过期 | **SUSPECT** | 标记节点为可疑，停止分发新任务。 |
| **SUSPECT** | 收到该节点心跳包 | **ACTIVE** | 恢复正常状态。 |
| **SUSPECT** | 持续 30s 处于 SUSPECT 状态 | **DEAD** | 彻底移除节点，启动 Failover。 |
| **DEAD** | Leader 扫描到未完成任务 | **REBALANCE** | 将该节点的 `pending/running` 任务重分配给其他 ACTIVE 节点。 |

## 4. 安全加固 (Security)
*   所有心跳包必须携带基于 `CLUSTER_SECRET` 的 HMAC-SHA256 签名。
*   节点在接收到广播时，必须校验签名，非法节点的心跳将被忽略。

## 5. 验收标准
1. `tests/test_failover_logic.py` 模拟节点宕机，任务在 45s 内被接管。
2. 审计流显示任务接管后状态连续，无重复执行。
