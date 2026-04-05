# Phase 7: Distributed Cluster & High Availability Pre-research (#60)

## 1. 目标 (Objectives)
将 OpsSentry 从单节点（或依赖共享文件系统的伪分布式）演进为真正的 **分布式集群架构**。
通过引入跨节点状态同步、故障自动转移（Failover）和负载均衡路由，实现“生产级、高可用、可水平扩展”的运维监控网络。

## 2. 核心架构选型 (Architectural Selection)

### 2.1 状态同步与节点发现 (State Sync & Node Discovery)
*   **方案 A: 中心化 Redis (推荐)**
    *   **理由**: 成熟的分布式锁 (Redlock)、Pub/Sub 广播机制（用于心跳和任务分发）及 Key-Value 存储。
    *   **适用场景**: 具有中心化管理后台（Sentry Hub）的中小规模集群。
*   **方案 B: 去中心化 Gossip (SWIM/Memberlist)**
    *   **理由**: 无单点故障，自发现，弹性极强。
    *   **适用场景**: 超大规模、跨地域、弱中心化的监控节点。
*   **架构决策**: 初期采用 **中心化 Redis 模式** 配合 **Gossip 探测** (双轨制)。Redis 作为任务仲裁与配置中枢；Gossip 负责节点间的实时存活感知（防止 Redis 抖动导致的脑裂）。

### 2.2 任务路由与负载均衡 (Task Routing & Load Balancing)
*   **Leader Election (领导者选举)**: 多个 Cron 节点通过 Redis 租约竞选 Leader。只有 Leader 负责生成任务指令。
*   **Consistency Hashing (一致性哈希)**: 将任务（如特定主机的巡检）按资源 ID 哈希分配给特定 Sentry 节点，确保任务执行的局部性与缓存命中率。
*   **Dynamic Partitioning**: 根据节点 CPU/内存负载实时重分配任务。

## 3. 分布式审计流聚合 (#62)
*   **Local Buffer + Ship**: 每个节点保留本地 SQLite (WAL Mode) 以应对网络隔离。
*   **Aggregator Service**: 异步将本地日志批量 Push 到中心化 ELK/ClickHouse 或集中的 OpsLedger (PostgreSQL)。

## 4. 故障转移协议 (Failover Protocol)
1.  **心跳超时**: 连续 N 次未收到心跳 -> 标记节点为 `SUSPECT`。
2.  **集群确认**: 多数节点确认节点 `DEAD`。
3.  **任务迁移**: Leader 将该节点的活跃任务重新分配给其他负载较低的节点。
4.  **状态恢复**: 节点重连后自动从中心存储拉取最新状态并对齐。

## 5. 物理资产变更预演
*   `src/cluster/`: 新增目录，包含 `node_manager.py`, `heartbeat.py`, `failover.py`。
*   `src/global_sync.py`: 升级为支持 RedisLock 的 `DistributedSyncBuffer`。
*   `src/main.py`: 增加集群模式开关与节点注册接口。

## 6. 后续行动建议 (Roadmap)
1.  **#61 (TL)**: 设计心跳包格式与广播频率。
2.  **#62 (Developer)**: 实现日志异步上报的原型。
3.  **#60 (Architect - Myself)**: 输出详细的集群通信序列图与 Redis Schema 设计。
