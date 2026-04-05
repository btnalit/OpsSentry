# Phase 7: Redis Schema & Failover Sequence Specification (#63)

## 1. Redis Key Schema 设计

为确保集群状态的一致性与可预测性，所有 Redis Key 均使用 `sentry:` 前缀。

| Key 模式 | 类型 | TTL | 说明 |
| :--- | :--- | :--- | :--- |
| `sentry:cluster:nodes` | Hash | 无 | 存储所有注册节点的元数据 `{node_id: json_metadata}` |
| `sentry:node:hb:{node_id}` | String | 30s | 节点心跳。TTL 失效则触发 SUSPECT 判定 |
| `sentry:leader:lease` | String | 15s | 集群 Leader 租约。只有持有该 Key 的节点可执行任务分发与故障转移 |
| `sentry:task:lock:{task_id}` | String | 任务时长 | 分布式任务执行锁，防止同一任务被多个节点抢占 |
| `sentry:task:registry` | Hash | 无 | 记录当前活跃任务及其执行节点 `{task_id: node_id}` |
| `sentry:msg:broadcast` | Pub/Sub | - | 集群广播通道，用于发布配置变更或即时指令 |

## 2. 核心交互序列图 (Sequence Diagrams)

### 2.1 领导者选举 (Leader Election)
多个节点竞争 Leader 角色，确保集群内只有一个“指挥官”。

```mermaid
sequenceDiagram
    participant N1 as Node 1
    participant N2 as Node 2
    participant R as Redis
    
    N1->>R: SET sentry:leader:lease N1 NX EX 15
    R-->>N1: OK (Leader 诞生)
    N2->>R: SET sentry:leader:lease N2 NX EX 15
    R-->>N2: FAIL (已有 Leader)
    
    Note over N1: 执行任务分发与存活监控
    
    loop 每 10s 续约
        N1->>R: EXPIRE sentry:leader:lease 15
    end
```

### 2.2 故障自动转移 (Failover)
当执行节点宕机时，Leader 识别并重新分配任务。

```mermaid
sequenceDiagram
    participant LN as Leader Node
    participant WN as Worker Node (Down)
    participant R as Redis
    participant TN as Target Node (Failover)
    
    Note over WN: 物理宕机，停止心跳
    R->>R: sentry:node:hb:WN 过期
    
    LN->>R: SCAN sentry:node:hb:*
    LN->>LN: 发现 WN 心跳缺失 (SUSPECT)
    
    Note over LN: 确认 WN 已死亡 (DEAD)
    
    LN->>R: HGET sentry:task:registry (查找 WN 的任务)
    R-->>LN: 返回 Task_X
    
    LN->>R: HDEL sentry:task:registry Task_X
    LN->>R: DEL sentry:task:lock:Task_X
    
    LN->>TN: 发布新任务指令 (Task_X)
    TN->>R: SET sentry:task:lock:Task_X NX
    TN->>R: HSET sentry:task:registry Task_X TN
    
    Note over TN: 开始执行被中断的任务
```

## 3. 容错细节 (Fault Tolerance Details)

*   **脑裂防护**: 节点在操作 Redis 前必须校验自己是否仍持有 `sentry:leader:lease`。如果由于 GC 停顿或网络抖动导致租约失效，节点必须立即停止所有管理动作。
*   **优雅停机**: 节点正常退出时，应主动调用 `DEL sentry:node:hb:{node_id}` 并将 `sentry:task:registry` 中属于自己的任务清理，触发即时重分配。
*   **隔离恢复 (Anti-Entropy)**: Leader 节点每 5 分钟执行一次全量同步，通过 `HGETALL sentry:task:registry` 与实际 Redis 锁进行对齐，清理因意外崩溃残留的死锁。

## 4. 后续任务分配建议
*   **Developer**: 请根据上述 Schema 扩展 `src/config_shield.py` 的分布式锁实现，支持 Redis 后端。
*   **Tech Lead**: 请在心跳协议设计中，包含 `node_id` 与 `current_load` 等指标。
