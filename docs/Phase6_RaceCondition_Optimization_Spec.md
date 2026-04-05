# Phase 6: Task #51 - Multi-Agent Race Condition & Arbitration Optimization (Research & Design)

## 1. 现状分析 (Current State)
在 Phase 6 #50 存储重构完成后，`OpsLedger` 依赖 **SQLite (WAL Mode)** 处理并发读写。
*   **读取**: WAL 模式允许并发读，互不阻塞。
*   **写入**: SQLite 在同一时刻仅允许一个写事务。
*   **并发保护**: `SQLiteLedgerStorage` 设置了 `busy_timeout=5000ms`，这能自动处理大部分短时间的写冲突（进程会自动重试直至超时）。
*   **局部锁**: `OpsLedger` 内部使用 `threading.RLock()`，但这仅限于进程内线程安全，无法处理跨 Agent（多进程）的竞态。

## 2. 潜在瓶颈与竞态场景 (Potential Bottlenecks & Race Conditions)

### 2.1 数据库锁定超时 (`database is locked`)
在高频并发场景（例如 20+ Agents 同时上报巡检结果）下，5秒的 `busy_timeout` 仍可能被耗尽，导致 `sqlite3.OperationalError`。
*   **后果**: Agent 任务失败，审计流水丢失或状态未更新。

### 2.2 逻辑层面的状态覆盖 (Status Overwrite)
两个 Agent 同时尝试更新同一个 `LedgerEntry`。
*   **场景**: 
    1. Agent A 读取 Entry (status="pending")。
    2. Agent B 读取 Entry (status="pending")。
    3. Agent A 执行 `transition(status="running")` 并成功。
    4. Agent B 执行 `transition(status="running")` 或其他状态。
*   **风险**: 如果业务逻辑依赖于状态转换的顺序（如 `VALID_TRANSITIONS`），非原子的“读取-校验-写入”可能导致逻辑错误。

## 3. 优化方案 (Proposed Optimizations)

### 3.1 增强型退避重试 (Exponential Backoff with Jitter)
在 `SQLiteLedgerStorage` 驱动层引入类似于 `ConfigShield` 的指数退避算法。
*   **逻辑**: 当捕获到 `OperationalError: database is locked` 时，不立即报错，而是等待一个随机抖动的时间后重试。
*   **参数**: `base_delay=0.01s`, `max_attempts=5`, `max_delay=0.5s`。

### 3.2 乐观并发控制 (Optimistic Concurrency Control)
在执行 `UPDATE` 操作时增加版本或时间戳校验。
*   **SQL 改动**: 
    ```sql
    UPDATE ledger SET status = ?, updated_at = ? 
    WHERE id = ? AND updated_at = ?; -- 仅当更新时间戳未变时更新
    ```
*   **处理**: 如果 `rowcount == 0`，说明数据已被其他 Agent 修改，需重新读取并重试逻辑。

### 3.3 数据库级别原子状态切换
将状态机转换逻辑下沉到 SQL 语句中，确保原子性。
*   **SQL 改动**:
    ```sql
    UPDATE ledger SET status = ?, updated_at = ? 
    WHERE id = ? AND status IN (<allowed_old_statuses>);
    ```

### 3.4 细粒度逻辑资源锁 (Integration with ConfigShield)
对于关键任务分录，在执行 `transition` 这种敏感操作前，通过 `ConfigShield` 锁定 **`ledger:entry:{entry_id}`** 资源。
*   **优点**: 将 SQLite 的数据库级锁（粗粒度）转换为资源级锁（细粒度）。
*   **代价**: 增加了一次文件系统 IO 锁定开销。

## 4. 实施优先级 (Priorities)
1.  **High**: 在 `SQLiteLedgerStorage` 中实现 **3.1 增强型退避重试** (捕获 OperationalError)。
2.  **Medium**: 在 `SQLiteLedgerStorage.update` 中实现 **3.3 原子状态切换** (将逻辑校验并入 WHERE 子句)。
3.  **Low**: 评估是否需要 **3.4 资源级锁** (仅针对极端冲突任务)。

## 5. 结论 (Conclusion)
Phase 6 #51 的核心应聚焦于 **“优雅降级”** 和 **“原子校验”**。通过将部分业务逻辑（状态转换校验）下沉至数据库层，并配合退避算法，可极大提升 OpsSentry 在超大规模 Agent 部署下的稳定性。
