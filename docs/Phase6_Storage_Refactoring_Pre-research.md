# OpsSentry Phase 6: Storage Refactoring Pre-research (v1.0)

> **Document**: [DOCS/Phase6_Storage_Refactoring_Pre-research.md](DOCS/Phase6_Storage_Refactoring_Pre-research.md)
> **Author**: Architect (系统架构师)
> **Date**: 2026-04-04
> **Status**: Approved for Prototype

## 1. 现状评估 (Current State)

目前的 `OpsLedger` 采用基于 JSON 的文件存储模式。
- **写入复杂度**: $O(N^2)$。每次写入都需要读取全量数据、解析 JSON、更新内存对象、序列化并重写整个文件。
- **并发性能**: 依赖于 `LockedSyncBuffer` 的文件级互斥锁。在高频审计场景下，I/O 争用会成为系统瓶颈。
- **查询能力**: 仅支持基于内存的简单过滤，缺乏复杂的关联查询与聚合分析能力。

## 2. 演进目标 (Evolution Objectives)

为支持 Phase 6 的大规模分布式扩展，存储层必须具备：
1. **原子追加 (Atomic Append)**: 写入开销应为 $O(1)$。
2. **并发安全 (Concurrency)**: 支持多进程、多线程的安全访问（尤其是 WAL 模式）。
3. **高效检索 (Indexed Search)**: 支持对 `node_id`, `ts`, `action` 等字段的索引查询。
4. **嵌入式部署 (Zero-Config)**: 维持“零配置”安装体验，无需独立数据库服务器。

## 3. 技术选型对比 (Technical Options)

| 特性 | DuckDB | SQLite (WAL Mode) | JSONL (Append-only) |
| :--- | :--- | :--- | :--- |
| **主要定位** | OLAP (分析型) | OLTP (事务型) | 结构化日志 |
| **写入性能** | 极快 (列式压缩) | 快 (行式追加) | 极快 (简单 IO) |
| **查询性能** | 极强 (向量化执行) | 强 (索引支持) | 弱 (需全扫描) |
| **并发模型** | 单写多读 | 多写多读 (WAL) | 依赖外部锁 |
| **持久化** | 强 (单一文件) | 极强 (事务支持) | 一般 |

### 3.1 方案推荐：SQLite (WAL Mode)
**理由**: 
- `OpsLedger` 的本质是审计追踪（Audit Trail），属于典型的 OLTP 写入负载。
- SQLite 的 **WAL (Write-Ahead Logging)** 模式完美解决了读写冲突问题，且支持 TB 级数据存储。
- Python 标准库内置支持，无需新增依赖。

### 3.2 进阶方案：DuckDB
**理由**: 
- 如果未来需要对数百万条审计流水进行“运维趋势分析”或“异常检测算法”，DuckDB 的列式存储优势将无可替代。
- 建议作为“分析插件”可选接入，而非主 Ledger 存储。

## 4. 架构重构路径 (Refactoring Path)

1. **抽象存储层接口**: 定义 `LedgerStorage` 接口（`append`, `query`, `get_by_id`）。
2. **实现 SQLite 驱动**: 
    - 使用 `sqlite3` 模块实现驱动。
    - 建立 `ledger` 表，对 `timestamp` 和 `action_type` 建立索引。
3. **数据迁移**: 提供脚本将现有的 `ops_ledger.json` 转换为 SQLite 格式。
4. **性能验证**: 执行 10 万级记录的并发写入压测。

---

**Architect's Final Verdict**: 
Phase 6 应优先将 `OpsLedger` 存储层迁移至 **SQLite (WAL Mode)**。这能彻底消除目前 $O(N^2)$ 的写放大问题，并为分布式集群提供稳固的数据一致性保障。
