# OpsSentry Phase 6: Data Integrity & Performance Audit Standard (SQLite)

**Document ID**: Audit_Standard_SQLite.md  
**Scope**: Phase 6 #50 - Storage Refactoring (JSONL to SQLite WAL)  
**Auditor**: QA Auditor (代码审计与测试专家)

## 1. 验收红线 (Critical Redlines)
任何不满足以下红线的代码实现将直接予以 **[REJECT]**：
1. **0 数据丢失 (Zero Data Loss)**: 迁移过程必须保证原始 JSONL 数据的条数、内容（含时间戳精度）与新 SQLite 库完全一致。
2. **ACID 事务保障**: 每一条审计流水（Audit Entry）的写入必须是原子性的。禁止出现部分写入或断电导致的文件损坏（需验证 `PRAGMA synchronous = NORMAL/FULL`）。
3. **并发死锁预防**: 必须正确处理 `sqlite3.OperationalError: database is locked`。代码中必须包含明确的 `busy_timeout` 设置或重试退避逻辑。

## 2. 静态代码审计项 (Static Analysis Checklist)
在代码审查阶段，我将重点检查：
- [ ] **WAL 模式配置**: 是否显式执行了 `PRAGMA journal_mode=WAL;`。
- [ ] **连接池/单例管理**: 跨进程/线程环境下，SQLite 连接的打开与关闭是否规范，是否存在连接泄露。
- [ ] **参数化查询**: 严禁拼接 SQL 字符串，所有写入必须使用 `?` 参数化占位符以防止 SQL 注入。
- [ ] **索引策略**: 是否对 `timestamp`, `node_id`, `action_type` 等高频查询字段建立了索引（`CREATE INDEX`）。
- [ ] **异常回滚**: 在 `try-except` 块中是否包含 `connection.rollback()` 以处理写入失败的情况。

## 3. 动态压测验收指标 (Dynamic Performance Metrics)
重构后的 `OpsLedger` 需通过 `tests/stress_ledger_v2.py` 的专项压测：
- **写入性能**: 10 万条记录的顺序写入耗时应比原 JSONL 模式提升 50 倍以上（由于去除了 $O(N^2)$ 的全量重写）。
- **并发冲突率**: 在 10 个进程并发写入 10,000 条数据时，`database is locked` 导致的失败率应为 0%（需具备自动重试机制）。
- **空间占用**: 监测 `.db-wal` 临时文件的大小，确保 checkpoint 机制正常工作，防止磁盘空间被预写日志撑爆。

## 4. 迁移验证流程 (Migration Verification)
1. **校验和对比**: 计算原有 `ops_ledger.json` 的数据指纹。
2. **导入测试**: 执行 `scripts/migrate_to_sqlite.py`。
3. **一致性检查**: 使用 `SELECT COUNT(*)` 和 `SELECT SUM(LENGTH(payload))` 对比新旧库数据量，确保无字符集截断。

---
**QA Verdict**: 只有通过上述所有维度的物理验证，存储重构任务才会被标记为 **[COMPLETED]**。
