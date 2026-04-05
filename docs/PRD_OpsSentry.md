# OpsSentry (运维哨兵) 产品需求文档 (PRD)

> **文档版本**：v2.1 | **最后更新**：2026-03-31
> **变更说明**：v2.1 聚焦修正——将 v2.0 的通用平台定位收紧至 **IT 运维专用场景**；剔除电商/选品/图像媒体工具组；重写定时任务模板为运维巡检场景；重写 Agent 示例为运维角色。

---

## 1. 项目愿景

OpsSentry v2.1 是一个运行在 **Linux Docker 容器**内的、面向 **IT 运维团队**的智能体自动化平台。

它将 Accio 的多智能体协作能力与企业运维场景深度融合，通过 **REST API + WebSocket** 对外暴露，实现：

- **去桌面化**：纯 Linux + Docker 部署，无 Electron/Windows 依赖
- **运维自治**：Agent 自主执行巡检、告警响应、故障诊断、变更审批等运维任务
- **端侧可靠**：继承 v1.1 的持久化/锁机制，断网后核心能力 100% 可用
- **团队协作**：多 Agent 分工协同（告警分拣 Agent、根因分析 Agent、变更执行 Agent）

### 典型使用场景

| 场景 | 描述 |
|---|---|
| **主动巡检** | 定时触发 Agent 检查服务健康、磁盘/CPU/内存水位、证书到期 |
| **告警响应** | 告警事件路由至对应 Agent，自动执行初步诊断（日志分析/进程检查） |
| **故障处置** | Agent 查询知识库（Runbook），生成处置建议，高风险操作请求人工审批 |
| **变更审批** | ConfigShield 锁定目标资源，Agent 执行变更，写回审计日志 |
| **日报/周报** | 定时汇总告警统计、SLO 达成情况，通过渠道推送给值班人员 |

---

## 2. 核心功能需求

### 2.1 智能体管理 (Agent Management)

#### 2.1.1 智能体创建与配置
通过 API 创建运维智能体，必填字段：

- `name`：智能体名称（如 `巡检哨兵`、`告警分拣器`、`变更执行者`、`根因分析师`）
- `description`：职责描述
- `vibe`：风格枚举（`professional` / `expert` / `balance`）
- `model_provider`：模型提供商（`claude` / `openai` / `qwen` / `moonshot` / `zhipu` / `minimax` / `auto`）
- `model_id`：具体模型（如 `claude-sonnet-4-6`、`gpt-4o`、`qwen-max`）
- 创建后自动生成 `~/.accio/accounts/<uid>/agents/<did>/agent-core/` 目录结构

#### 2.1.2 工具关联 (Tool Binding)

**运维场景工具组**（按用途分类，可按 Agent 角色启用/禁用）：

| 工具组 | 包含工具 | 适用 Agent 角色 |
|---|---|---|
| **文件系统** | List / Read / Grep / Glob / Ripgrep / Write / Edit | 所有 Agent |
| **命令执行** | Bash / Process | 巡检 Agent、变更执行 Agent |
| **网络诊断** | Web Fetch（用于 HTTP 健康检查/API 探测） | 巡检 Agent |
| **定时调度** | Cron（内部触发） | 巡检 Agent |
| **问询确认** | Question（高风险操作前人工确认） | 变更执行 Agent |
| **记忆与规划** | Memory Search / Memory Get / Task Create / Task Get / Task Update / Task List | 所有 Agent |
| **Agent 协作** | Sessions Spawn / Sessions List / Sessions History / Sessions Send | 编排 Agent、值班 Agent |
| **外部集成** | MCP Call（对接 Prometheus/Grafana/PagerDuty/JIRA MCP Server） | 告警 Agent、报告 Agent |
| **通知推送** | Gmail（邮件告警通知） | 值班 Agent |

> **明确排除**（运维场景不适用）：Product Supplier Search、Image Generate、Image Edit、See Image、Web Search（无监督爬网）、Weather、Location

- 工具配置持久化至 `agent-core/tool-registry.jsonc`

#### 2.1.3 技能关联 (Skill Binding)

**预置运维技能库**（存放于 `skills/` 目录，按需绑定）：

| 技能名 | 功能描述 |
|---|---|
| `log-analyzer` | 日志模式识别：ERROR/WARN 聚类、异常 spike 检测 |
| `runbook-retriever` | Runbook 知识库检索（基于 KnowledgeCore BM25） |
| `service-health-check` | HTTP/TCP 健康检查，返回结构化状态报告 |
| `metric-interpreter` | Prometheus/Grafana 指标解读与阈值告警分析 |
| `incident-reporter` | 告警事件结构化报告生成（标题/影响/根因/处置建议） |
| `change-auditor` | 变更操作前合规审查，输出风险评分 |
| `cert-expiry-checker` | SSL/TLS 证书到期扫描 |
| `disk-cleanup-advisor` | 磁盘空间分析，给出清理建议（不自动删除） |

#### 2.1.4 核心文件自定义 (Core Configuration Files)

通过 API 读写以下文件：

| 文件 | 运维场景用途示例 |
|---|---|
| `SOUL.md` | Agent 核心原则（如"不得在未获审批的情况下执行破坏性命令"） |
| `IDENTITY.md` | Agent 角色定义（如"你是值班 SRE，负责 K8s 集群的一线告警响应"） |
| `AGENTS.md` | 团队协作规则（如"高风险操作必须转发给变更审批 Agent"） |
| `MEMORY.md` | 长期积累的运维知识（已知故障模式、常见误报规则）|
| `USER.md` | 服务对象描述（如"你服务的是 Ops 团队，值班人员为中国时区"） |

---

### 2.2 定时任务 (Cron Jobs)

**调度类型**（4 种，与 Accio 原生对齐）：

- `in`：延迟触发（如"10 分钟后发起一次巡检"）
- `at`：指定时间点（如"每天 08:00 生成值班日报"）
- `every`：固定间隔（如"每 5 分钟探测一次服务存活"）
- `cron`：标准 cron 表达式（5/6 字段，支持时区）

**Payload 类型**（3 种）：

- `command`：执行 Shell 命令（如 `df -h`、`systemctl status nginx`）
- `tool`：调用已注册工具（如调用 MCP Call 查询 Prometheus 告警）
- `agent`：触发指定 Agent 执行 prompt（主要方式）

**预置运维任务模板**：

| 模板名 | 调度示例 | Agent Prompt 示例 |
|---|---|---|
| **服务存活巡检** | `every 5min` | "对 services.yaml 中所有服务执行 HTTP 健康检查，失败的立即写入 OpsLedger 并通知值班人员" |
| **磁盘水位告警** | `cron: 0 */4 * * *`（每 4 小时） | "检查所有受管节点磁盘使用率，超过 85% 的生成清理建议报告" |
| **证书到期扫描** | `cron: 0 9 * * 1`（每周一 09:00） | "扫描 certs/ 目录下所有证书，30 天内到期的通过邮件告警" |
| **日志异常巡检** | `cron: 0 * * * *`（每小时） | "分析过去 1 小时的 /var/log/app/*.log，统计 ERROR 数量，超阈值生成事件" |
| **SLO 日报** | `cron: 30 8 * * *`（每天 08:30） | "从 Prometheus 拉取过去 24h SLO 指标，生成值班日报并发送至 ops-team@example.com" |
| **Runbook 知识库同步** | `cron: 0 2 * * *`（每天 02:00） | "拉取 runbooks/ 目录最新文件，重建 KnowledgeCore BM25 索引" |
| **待处理告警汇总** | `cron: 0 9,18 * * *`（每天 9:00 和 18:00） | "查询 OpsLedger 中 status=pending 的告警事件，汇总后推送给值班人员" |

- **任务存储**：`~/.accio/cron/jobs.json`（与 Accio 原生路径对齐）
- **执行日志**：`~/.accio/cron/runs/<job-id>.jsonl`
- **单次任务**：`deleteAfterRun: true` 执行后自动清理

---

### 2.3 技能系统 (Skills)

- **技能发现**：列出已安装的运维技能（含版本号、描述、触发关键词）
- **技能创建**：上传 `SKILL.md` + 相关脚本资源，创建新运维技能
- **技能启用/禁用**：控制是否注入 Agent System Prompt
- **热加载**：新技能无需重启服务即时生效

**存储路径**：
- Agent 私有技能：`agent-core/skills/<skill-name>/SKILL.md`
- 账户级共享技能：`~/.accio/accounts/<uid>/skills/<skill-name>/SKILL.md`

---

### 2.4 会话管理 (Session Management)

#### 2.4.1 单体 Agent 对话
- WebSocket / SSE 流式接口
- 会话历史持久化（`~/.accio/sessions/<session-id>/history.jsonl`）
- Token 使用率达 60% 阈值时自动触发上下文压缩

**典型使用**：值班人员通过 API 直接与"根因分析师" Agent 对话，描述故障现象，Agent 调用工具查询日志/指标后给出诊断结论。

#### 2.4.2 多 Agent 团队协作 (Group Session)
- 创建群聊会话，关联多个运维 Agent
- `@mention` 触发指定 Agent 响应
- MessageRouter 消息总线：Agent 间异步通信，通过 OpsLedger 解耦
- 群聊历史对所有成员 Agent 可见

**典型协作链**：
```
值班人员发送告警信息
    → @告警分拣器 判断严重程度、归类
    → @根因分析师 执行日志/指标分析
    → @变更执行者 (需审批) 执行修复操作
    → @巡检哨兵 验证服务恢复
```

---

### 2.5 消息渠道 (Channels) — Phase 3

运维告警/报告通知推送：

- **飞书** / **钉钉**：企业内部告警推送（webhook + bot）
- **Telegram**：轻量级通知
- **Email (Gmail/SMTP)**：正式告警邮件
- 渠道消息入站（如值班人员在飞书回复指令）→ 路由至指定 Agent 处理

---

### 2.6 端侧自治能力（继承 v1.1）

- **OpsLedger**：运维事件独立账本（`data/ops-queue/ledger.jsonl`），断点续传
- **ConfigShield**：变更操作资源锁（TTL + 心跳续期 + 原子抢占）
- **KnowledgeCore**：Runbook/故障知识库本地 BM25 检索（`data/knowledge/`）
- **离线降级**：网络不可达时，巡检/诊断/知识库查询全部可用

---

## 3. 用户角色

| 角色 | 描述 |
|---|---|
| **SRE / 值班工程师** | 发起对话、查看告警、审批高风险操作 |
| **运维管理员 (Admin)** | 创建/删除 Agent，管理技能，配置定时任务，审批策略 |
| **运维智能体 (Agent)** | 系统内自治执行单元：巡检/告警响应/诊断/变更/报告 |

---

## 4. 关键技术指标

| 指标 | 目标值 |
|---|---|
| Agent 创建响应 | < 500ms |
| 单体对话首 token 延迟 | < 2s（取决于 LLM 提供商） |
| 服务重启后状态恢复 | < 5s |
| Runbook 知识库检索（BM25） | < 100ms（10GB 内） |
| 定时任务调度精度 | ±2s（APScheduler 实现） |
| 本地锁 TTL | 默认 30s，心跳续期 10s |
| 离线降级覆盖率 | 巡检/诊断/RAG 100% 可用 |

---

## 5. 非功能性需求

- **部署**：`docker-compose up` 一键启动，零额外依赖
- **持久化**：Docker Volume 挂载，容器重建不丢数据
- **多模型**：LiteLLM 统一接口，支持 Claude / OpenAI / Qwen / Moonshot / Zhipu / MiniMax
- **安全审计**：Bash 工具调用经 NsJailRunner（nsjail namespace + Seccomp）+ Policy 审计三层防护；高风险命令（`rm -rf` / `dd` / `mkfs`）Policy L1 硬拒绝
- **变更合规**：所有写操作通过 ConfigShield 加锁，释放后写审计日志
- **技能热加载**：新技能无需重启

---

## 6. 功能范围（MVP 边界）

### Phase 1 — 基础骨架 ✅（已完成）
OpsLedger / KnowledgeCore / ConfigShield / SyncBuffer / Security 基线

### Phase 2 — 服务核心（当前）
Agent CRUD API + AgentVM 推理回路 + ToolRegistry + 单体对话 WebSocket + Dockerfile

### Phase 3 — 完整运维能力
定时巡检任务（CronEngine）+ 运维技能系统（SkillLoader）+ 多 Agent 协作（GroupSession + MessageRouter）

### Phase 4 — 全局互联
GlobalSync 多节点同步 + ConfigShield 分布式锁 + 飞书/钉钉/Telegram 渠道接入
