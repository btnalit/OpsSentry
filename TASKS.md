# OpsSentry (运维哨兵) 落地路线图

> **文档版本**：v1.1 | **最后更新**：2026-03-31
> **变更说明**：基于架构审查（Task #1）修正任务描述，明确阶段划分与模块入口路径。

本项目基于 Accio 的分布式自主架构，旨在实现企业级的端侧自治与全局同步。

---

## 📋 核心开发任务

### Phase 1 — 本地单节点（无网络依赖，优先落地）

| 任务 ID | 任务主题 | 核心说明 | 入口文件 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **#1** | **OpsLedger (持久化)** | 基于 `data/ops-queue/ledger.jsonl` 实现独立指令账本与断点续传。**不复用** Accio 原生 `task.jsonl`（加载即删除语义冲突）。状态机字段：`pending/running/completed/failed` + `checkpoint`。 | `src/ops_ledger.py` | ⏳ Pending |
| **#2** | **KnowledgeCore (RAG)** | 构建 BM25 本地故障库，知识存储路径为 `data/knowledge/`（与 `data/memory/` 隔离），支持离线诊断。 | `src/knowledge_core.py` | ⏳ Pending |
| **#3** | **Security Sandbox (基线)** | 生成 `config/seccomp-default.json` 和 `config/policy-default.jsonl` 策略基线文件；Windows 端对齐 Accio 现有环境污染 + stub 方案。 | `config/` | ⏳ Pending |

### Phase 2 — 本地锁扩展

| 任务 ID | 任务主题 | 核心说明 | 入口文件 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **#4** | **ConfigShield (本地锁)** | 扩展 `DirectoryLockGate`，实现带 TTL（默认 30s）+ 心跳续期的本地文件锁（`data/locks/<hash>.lock`）；预留 `on_lock_acquired()` 回调供 Phase 3 注入分布式通知。**暂不实现** WebSocket 跨节点锁。 | `src/config_shield.py` | ⏳ Pending |

### Phase 3 — 联网功能（Phase 1/2 稳定后）

| 任务 ID | 任务主题 | 核心说明 | 入口文件 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **#5** | **GlobalSync (同步总线)** | 实现端侧与中控台的加密 WebSocket 消息总线；消息体含 `schema_version: "1.0"` + `ts`；离线缓冲至 `data/ops-queue/sync-buffer.jsonl`，恢复后重放。 | `src/global_sync.py` | ⏳ Pending |
| **#6** | **ConfigShield 分布式升级** | 在 Phase 4 本地锁基础上，接入 GlobalSync 实现跨节点 CMDB 资源锁。 | `src/config_shield.py` | ⏳ Pending |

### 验证

| 任务 ID | 任务主题 | 核心说明 | 状态 |
| :--- | :--- | :--- | :--- |
| **#7** | **Verification (验证)** | 模拟断电（OpsLedger 恢复 < 5s）、并发冲突（ConfigShield TTL 超时释放）与大规模运维压力测试（BM25 10GB < 100ms）。 | ⏳ Pending |

---

## 📂 目录结构参考

```
OpsSentry/
├── config/
│   ├── seccomp-default.json      # Linux Seccomp 系统调用白名单
│   └── policy-default.jsonl      # L1/L2/L3 三级安全策略基线
├── data/
│   ├── ops-queue/
│   │   ├── ledger.jsonl          # OpsLedger 独立账本（断点续传）
│   │   └── sync-buffer.jsonl     # GlobalSync 离线缓冲队列
│   ├── locks/                    # ConfigShield 本地锁文件目录
│   ├── knowledge/                # KnowledgeCore 运维知识库（BM25 索引）
│   └── memory/                   # Agent 个人记忆（与 knowledge/ 隔离）
├── docs/
│   ├── PRD_OpsSentry.md
│   └── SDD_OpsSentry.md
├── skills/                       # 运维场景自动化脚本
└── src/
    ├── ops_ledger.py             # OpsLedger 核心实现
    ├── knowledge_core.py         # KnowledgeCore BM25 实现
    ├── config_shield.py          # ConfigShield 锁机制
    └── global_sync.py            # GlobalSync WebSocket 同步
```

---

*注：可通过 `task_list` 命令在系统中实时查看进度。*
