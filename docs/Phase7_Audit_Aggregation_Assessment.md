# Phase 7: Distributed Audit Stream Aggregation Assessment (#62)

## 1. 背景与目标
在 OpsSentry 分布式集群中，每个节点（Worker）都持有本地的 SQLite 审计账本（OpsLedger）。为了实现全局可观测性，需要将这些分散的审计流实时（或准实时）聚合到中心化 HUD。
核心要求：
- **高性能**：不干扰本地任务执行的延迟。
- **高可用**：在网络分区（Network Partition）期间，数据必须在本地暂存。
- **一致性**：恢复连线后，支持“断点续传”，确保审计流不丢失、不重写。

## 2. 方案对比：Push vs. Tail

| 方案 | 机制 | 优点 | 缺点 |
| :--- | :--- | :--- | :--- |
| **Inline Relay (Push)** | 在 `OpsLedger` 执行 `append/update` 时同步或异步调用上报接口。 | 实时性最高；逻辑直观。 | 增加主流程延迟风险；网络抖动可能导致堆栈阻塞或丢失上报失败的数据。 |
| **Background Shipper (Tail)** | 独立线程定期轮询本地 SQLite，读取未上报的增量数据进行 Batch 上报。 | **完全解耦**；天然支持断网暂存；支持批量发送，效率更高。 | 存在秒级以内的感知延迟。 |

**结论**：采用 **Background Shipper (Tail)** 方案。该方案符合 OpsSentry 的“韧性优先”原则，即使中心节点宕机，本地 Worker 仍能正常工作并安全记录所有操作。

## 3. 详细设计 (Architecture Design)

### 3.1 传输机制：Redis Streams
利用 Redis Streams 实现分布式的日志总线：
- **Key**: `sentry:audit:stream:{node_id}`
- **消息结构**: `{"entry": json_ledger_entry, "ts": timestamp}`
- **优点**: Redis Streams 内置了消息持久化与多消费者模型，方便 HUD 与其他审计工具并发消费。

### 3.2 节点端：OpsShipper 逻辑
每个节点运行一个后台线程 `OpsShipper`：
1. **状态记录**：在本地维护一个 `data/ops-queue/shipper.checkpoint` 文件，存储 `last_shipped_id`。
2. **扫描增量**：
   ```sql
   SELECT * FROM ledger WHERE created_at > ? OR (created_at = ? AND id > ?) ORDER BY created_at, id ASC LIMIT 100
   ```
3. **可靠上报**：
   - 将数据推送到 Redis Stream。
   - 收到确认（ACK）后，原子更新 `shipper.checkpoint`。
   - 如果网络失败，进入指数退避重试（Exponential Backoff）。

### 3.3 中心端：Aggregator 逻辑
中心节点（或 HUD 后端）负责消费所有节点的 Streams，并将其持久化到全局历史库或实时推送到前端。

## 4. 脑裂与分区应对
- **Network Partition**: Shipper 会在本地 SQLite 中持续积累数据。一旦链路恢复，Shipper 会从 `checkpoint` 位置自动重传。
- **Duplicate Prevention**: 由于每条 `LedgerEntry` 都有唯一的 `id`，消费端可以利用 Redis 或数据库的唯一约束进行幂等处理。

## 5. 后续行动 (Next Steps)
- [ ] 开发 `src/cluster/shipper.py` 原型。
- [ ] 在 `OpsLedger` 中预留 `last_updated_at` 字段以优化扫描性能（当前已有 `updated_at`）。
- [ ] 编写断网模拟压测脚本，验证 10k 条记录的断点续传完整性。
