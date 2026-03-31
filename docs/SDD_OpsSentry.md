# OpsSentry (运维哨兵) 技术设计文档 (SDD)

> **文档版本**：v1.1 | **最后更新**：2026-03-31
> **变更说明**：基于 Coder 架构审查结论（Task #1）修正以下缺口：
> - G1: OpsLedger 独立账本路径，与 Accio TaskQueue 隔离
> - G2: ConfigShield 增加 Phase 分级 + 本地锁 TTL + 离线降级策略
> - G3: Security Sandbox 对齐 Accio 已有 Windows 实现路线
> - G4: KnowledgeCore 独立存储路径，与 Agent memory/ 隔离
> - G6: GlobalSync 消息体增加 schema_version + ts 字段

---

## 1. 总体设计原则
基于 Accio 的 **RAMP (Reasoning, Action, Memory, Persistence)** 模型进行增强。
- **R (Reasoning)**: AgentVM 推理回路。
- **A (Action)**: 安全审计后的工具分发 (Capability Wrapper)。
- **M (Memory)**: 分布式热缓存 + 本地 BM25 离线索引。
- **P (Persistence)**: 原子化 OpsLedger (基于独立 jsonl 的状态机，与 Accio TaskQueue 隔离)。

---

## 2. 核心架构组件

### 2.1 OpsLedger (持久化总线)

> **[G1 修正]** OpsLedger 独立维护账本文件，**不复用** Accio 原生的 `.accio/agents/msg-queue/task.jsonl`。
> Accio TaskQueue 的"加载即删除"语义与 OpsLedger 断点续传语义相悖，二者必须物理隔离。

- **独立账本路径**：`data/ops-queue/ledger.jsonl`
- **状态机字段**：每条记录包含 `status`（`pending` / `running` / `completed` / `failed`）+ `checkpoint`
- **执行逻辑**：
  1. 动作执行前先写入 `ledger.jsonl`，状态置为 `running`
  2. 执行成功后原地更新 `status: completed`
  3. 节点重启后扫描 `ledger.jsonl`，捞出 `status: running` 的记录从 `checkpoint` 恢复
- **与 Accio 的关系**：通过 `accio_task_ref` 字段单向引用 Accio 任务 ID，不做双向绑定

**ledger 记录格式示例**：
```json
{
  "id": "UUID",
  "accio_task_ref": "ACCIO-TASK-UUID",
  "action": "restart_nginx",
  "status": "running",
  "checkpoint": { "step": 2, "last_output": "nginx: reloading config" },
  "created_at": 1743000000000,
  "updated_at": 1743000001234
}
```

---

### 2.2 ConfigShield (资源锁机制)

> **[G2 修正]** 分阶段实现，Phase 1 只做本地文件锁；分布式 WebSocket 锁推迟到 Phase 2。
> 核心设计原则：**断网时本地锁必须正常工作**，不能因为中控台不可达而阻塞执行。

#### Phase 1（当前实现目标）— 本地文件锁
- **继承**：扩展 Accio `DirectoryLockGate` 逻辑
- **锁文件路径**：`data/locks/<resource_hash>.lock`
- **锁记录字段**：`node_id`、`resource_path`、`acquired_at`、`ttl_ms`（默认 30000ms）
- **TTL 自动释放**：锁文件超过 `ttl_ms` 未续期则视为失效，下一个申请者可强制获取
- **死锁保护**：持锁方每 10s 写入心跳（`heartbeat_at`），超时未续期即视为节点崩溃

#### Phase 2（后续升级）— 分布式跨节点锁
- 本地锁成功后，通过 WebSocket 向中控台注册全局锁
- CMDB 资源标签锁定：防止不同节点对同一逻辑资源（如同一台服务器的 nginx.conf）并发修改
- 接口预留：Phase 1 代码中暴露 `on_lock_acquired(resource, node_id)` 回调，Phase 2 在此注入 WS 通知

#### 离线降级策略
- 中控台不可达时，自动 fallback 到本地锁模式
- 降级状态写入 `data/ops-queue/ledger.jsonl`，待网络恢复后上报冲突检测结果

---

### 2.3 KnowledgeCore (RAG 增强)

> **[G4 修正]** 知识库与 Agent 个人记忆物理隔离，防止 BM25 索引污染。

- **算法**：本地内存加速的 BM25 索引
- **知识库路径**：`data/knowledge/`（运维故障手册、排障文档）
- **Agent 记忆路径**：`data/memory/`（Agent 执行历史、上下文记忆，保持不变）
- **索引粒度**：Markdown 按 H2/H3 分块，支持自定义权重评分（`priority_score` 字段）
- **性能目标**：10GB 以内知识库，BM25 首词检索延迟 < 100ms

---

### 2.4 Security Sandbox (执行网关)

> **[G3 修正]** Windows 实现路线对齐 Accio 现有方案，不另起炉灶。

- **Linux**：Seccomp + Landlock（策略基线文件：`config/seccomp-default.json`）
- **Windows**：
  - **Phase 1**：对齐 Accio 已有方案——环境变量污染 + stub 脚本阻止危险二进制执行
  - **Phase 2**：按需升级为 Job Objects 资源限制 + 进程链审计
- **策略基线文件**（须在 `config/` 下提供）：
  - `config/seccomp-default.json`：Linux 系统调用白名单
  - `config/policy-default.jsonl`：L1/L2/L3 三级策略初始规则

---

## 3. 全局同步协议 (Communication Protocol)

### 3.1 消息格式 (JSON)

> **[G6 修正]** 增加 `schema_version` 和 `ts` 字段，保证协议向后兼容。

```json
{
  "schema_version": "1.0",
  "ts": 1743000000000,
  "nodeId": "SENTRY-01",
  "msgType": "STATE_SYNC",
  "payload": {
    "taskId": "UUID",
    "status": "IN_PROGRESS",
    "step": 3,
    "thought": "检测到磁盘空间 > 90%，准备清理日志。"
  }
}
```

**msgType 枚举**：`STATE_SYNC` / `LOCK_ACQUIRE` / `LOCK_RELEASE` / `POLICY_PUSH` / `AUDIT_LOG`

### 3.2 路由机制
- **主链路**：WebSocket (wss) 实时双向通信
- **备用链路**：MQTT / NATS（消息体格式相同，schema_version 保证兼容）
- **离线缓冲**：网络不可达时消息缓存至 `data/ops-queue/sync-buffer.jsonl`，恢复后重放

---

## 4. 安全决策模型 (Policy)
- **层级化 Policy**：
  - L1 (System Default): 全局硬性禁止（`rm -rf /`、`format`、`dd` 等危险命令）
  - L2 (Role Based): 根据节点角色（如 DB/Web）动态下发的路径权限，存储在 `config/policy-default.jsonl`
  - L3 (Human Approval): 触发变动敏感路径时挂起，索要 VICTOR 授权

---

## 5. 实现阶段规划

| 阶段 | 模块 | 依赖 | 说明 |
|------|------|------|------|
| Phase 1 | OpsLedger + KnowledgeCore + Security Sandbox (基线) | 无 | 本地单节点，无网络依赖，优先落地 |
| Phase 2 | ConfigShield (本地锁 + TTL) | Phase 1 | 本地文件锁，预留分布式接口 |
| Phase 3 | GlobalSync (WebSocket) + ConfigShield 分布式升级 | Phase 2 | 联网功能，此时 Phase 1/2 已稳定 |
