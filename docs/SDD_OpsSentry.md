# OpsSentry (运维哨兵) 技术设计文档 (SDD)

> **文档版本**：v2.1 | **最后更新**：2026-03-31
> **变更说明**：v2.1 新增轻量沙箱方案（nsjail/bwrap/direct 三级 SandboxProvider，替代 per-task Docker 方案）；修正 ToolRegistry Policy 格式说明；补全 Seccomp Python 运行时 syscall 白名单要求。v2.0 的七大核心模块设计不变。

---

## 1. 总体设计原则

基于 Accio 的 **RAMP (Reasoning, Action, Memory, Persistence)** 模型构建无头服务端。

| 层 | 职责 | 对应 Accio 原件 |
|---|---|---|
| **R (Reasoning)** | AgentVM 推理回路（Think-Act-Observe），驱动运维诊断/决策 | `AgentVM` |
| **A (Action)** | 工具注册 + 安全审计（Bash/MCP/HTTP探测）+ 技能执行 | `ToolRegistry` + `SecurityManager` |
| **M (Memory)** | Runbook/故障知识库 BM25 RAG + 会话上下文压缩 | `KnowledgeCore` + `LocalSessionService` |
| **P (Persistence)** | 运维事件 OpsLedger + 定时巡检 CronEngine + 会话历史 | `OpsLedger` + `CronEngine` |

---

## 2. 系统架构拓扑

```
┌─────────────────────────────────────────────────────┐
│                  外部接入层                           │
│  REST API (FastAPI)    WebSocket (群聊/单聊/流式)     │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│                  服务协调层                           │
│  AgentManager   SessionManager   CronEngine          │
│  SkillLoader    MessageRouter    ToolRegistry         │
└──────┬──────────────────────┬───────────────────────┘
       │                      │
┌──────▼──────┐   ┌───────────▼──────────────────────┐
│  AgentVM    │   │         持久化层                   │
│  (推理回路) │   │  OpsLedger  KnowledgeCore          │
│  LiteLLM    │   │  ConfigShield  SyncBuffer          │
└──────┬──────┘   └──────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│               文件系统 (Docker Volume)               │
│  ~/.accio/accounts/<uid>/agents/<did>/agent-core/   │
│  ~/.accio/cron/jobs.json                            │
│  ~/.accio/sessions/                                 │
│  data/ops-queue/   data/knowledge/   data/locks/    │
└─────────────────────────────────────────────────────┘
```

---

## 3. 核心模块设计

### 3.1 AgentManager（智能体管理器）

**职责**：智能体 CRUD，目录结构生成，配置持久化。

**存储路径**：
```
~/.accio/accounts/<uid>/agents/<did>/
└── agent-core/
    ├── SOUL.md
    ├── IDENTITY.md
    ├── AGENTS.md
    ├── MEMORY.md
    ├── USER.md
    ├── tool-registry.jsonc     ← 工具启用/禁用配置
    └── skills/                 ← Agent 私有技能目录
```

**Agent 配置模型**（`agent_config.json`，存储于 `agent-core/`）：
```json
{
  "did": "DID-XXXXXX-YYYYYY",
  "name": "巡检哨兵",
  "description": "负责定时对所有受管服务执行健康检查、日志扫描与磁盘水位告警",
  "vibe": "professional",
  "model_provider": "claude",
  "model_id": "claude-sonnet-4-6",
  "tools": {
    "file_system": true,
    "command_execution": true,
    "network_probe": true,
    "cron_trigger": true,
    "human_confirm": false,
    "memory_planning": true,
    "agent_collaboration": true,
    "external_integration": true,
    "notification": true
  },
  "skills": ["service-health-check", "log-analyzer", "cert-expiry-checker"],
  "created_at": 1743000000000,
  "updated_at": 1743000000000
}
```

**核心接口**：
```python
class AgentManager:
    def create_agent(config: AgentCreateRequest) -> AgentProfile
    def get_agent(did: str) -> AgentProfile
    def update_agent(did: str, patch: dict) -> AgentProfile
    def delete_agent(did: str) -> None
    def list_agents(uid: str) -> list[AgentProfile]
    def read_core_file(did: str, filename: str) -> str   # SOUL.md 等
    def write_core_file(did: str, filename: str, content: str) -> None
    def get_tool_registry(did: str) -> dict
    def update_tool_registry(did: str, tools: dict) -> None
    def bind_skill(did: str, skill_name: str) -> None
    def unbind_skill(did: str, skill_name: str) -> None
```

---

### 3.2 AgentVM（推理回路）

**职责**：驱动 Think-Act-Observe 闭环，调用 LLM，分发 Tool Call。

**对标**：Accio `AgentVM` 核心逻辑。

**推理回路**：
```
用户 Prompt
    │
    ▼
[Think] → LiteLLM 调用（流式输出）
    │
    ├── 有 tool_call？
    │       │
    │       ▼
    │   [Act] → ToolRegistry.dispatch(name, args)
    │       │
    │       ├── SecurityManager.audit() → 拒绝/放行
    │       │
    │       ▼
    │   [Observe] → 捕获执行结果，注入上下文
    │       │
    │       └──────────────────┐
    │                          ▼
    └── 无 tool_call？    继续 Think 回路
            │
            ▼
        Final Answer → 流式输出给客户端
```

**System Prompt 构建顺序**：
```
1. SOUL.md 内容
2. IDENTITY.md 内容
3. AGENTS.md 内容（团队协作规则）
4. tool-registry.jsonc 工具描述（启用的工具）
5. 已绑定技能的 SKILL.md 描述（动态拼接）
6. MEMORY.md 长期记忆
7. USER.md 用户画像
```

**上下文压缩（Context Compaction）**：
- Token 使用率达 60% 阈值时触发
- 生成压缩摘要替换历史消息，保留最新 N 条原始消息
- 压缩结果写入会话存储

**⚠️ tool_call 流式处理约束（关键）**：

LiteLLM `stream=True` 时，tool_call 内容分多个 chunk 传输（name 和 arguments 分批到达）。
**必须使用 accumulator buffer** 将同一 tool_call 的所有 chunk 完整合并（含 `name` + `arguments`）后，再调用 `ToolRegistry.dispatch()`。**禁止逐 chunk 调用工具**，否则 arguments 不完整会导致工具执行错误。

```python
# 正确实现示意
tool_call_buffer: dict[str, dict] = {}  # index → {name, arguments_str}

async for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.tool_calls:
        for tc in delta.tool_calls:
            buf = tool_call_buffer.setdefault(tc.index, {"name": "", "arguments": ""})
            if tc.function.name:
                buf["name"] += tc.function.name
            if tc.function.arguments:
                buf["arguments"] += tc.function.arguments
    elif chunk.choices[0].finish_reason == "tool_calls":
        # 所有 chunk 到齐，逐个 dispatch
        for idx, tc in tool_call_buffer.items():
            result = await tool_registry.dispatch(tc["name"], json.loads(tc["arguments"]))
```

**LiteLLM 多模型路由**：
```python
# 统一调用接口，屏蔽各 Provider SDK 差异
response = await litellm.acompletion(
    model=f"{provider}/{model_id}",
    messages=messages,
    stream=True,
    api_key=get_api_key(provider)
)
```

---

### 3.3 ToolRegistry（工具注册与审计）

**职责**：工具注册、权限审计、执行分发。对标 Accio `ToolRegistry` + `SecurityManager`。

**四层审计链**：
```
Tool Call 请求
    │
    ▼
[L1] 注册校验：工具名是否已注册？
    │
    ▼
[L2] 能力白名单：Agent 的 tool-registry.jsonc 是否启用该工具组？
    │
    ▼
[L3] Policy 正则：命令是否命中 policy-default.jsonl 的 deny 规则？
    │
    ▼
[L4] 执行审计：捕获 exitCode / stderr，命中 permission denied 则阻断
    │
    ▼
执行结果返回
```

**`config/policy-default.jsonl` 格式说明**（每行一条规则，JSON 格式）：

```json
{"level": "L1|L2|L3", "effect": "deny|allow|require_approval", "match": <MatchSpec>, "reason": "说明"}
```

`match` 支持以下三种类型（互斥，按 `level` 优先级顺序评估）：

| match 类型 | 字段 | 适用场景 | 示例 |
|---|---|---|---|
| `command_regex` | `{"command_regex": "<regex>"}` | bash 命令字符串匹配（L1 硬性禁止） | `"(^\\|\\\\s)(rm\\s+-rf\\s+/)"` |
| `node_role + path_prefix` | `{"node_role": "web", "path_prefix": "/etc/nginx"}` | 角色级路径授权（L2 动态下发） | web 节点允许操作 nginx 配置 |
| `path_regex` | `{"path_regex": "^/(etc\\|var\\|usr)/"}` | 敏感路径人工审批（L3 挂起） | 系统目录写操作需 VICTOR 确认 |

**effect 语义**：
- `deny`：立即拒绝，返回错误，不执行工具
- `allow`：明确放行，跳过后续 deny 规则（白名单优先）
- `require_approval`：挂起任务，写入 OpsLedger 等待管理员审批

> ⚠️ **实现注意**：L1（deny）优先级高于 L2（allow）。规则评估顺序：先过 L1 全部 deny 规则，再看 L2 allow，最后触发 L3 require_approval。不能简单按文件行序遍历。

**工具组映射**（`tool-registry.jsonc`）：

> 运维场景精简版，剔除电商/选品/图像类工具。

```jsonc
{
  "tool_groups": {
    // 日志/配置文件读写，所有 Agent 均开启
    "file_system":          ["list", "read", "grep", "glob", "ripgrep", "write", "edit"],

    // Shell 命令执行（systemctl/df/ps/netstat 等），巡检和变更 Agent 开启
    "command_execution":    ["bash", "process"],

    // HTTP/HTTPS 健康探测（web_fetch 只做 API 探测，不做网页爬取）
    "network_probe":        ["web_fetch"],

    // 内部定时触发（由 CronEngine 通过此工具驱动 Agent 定时任务）
    "cron_trigger":         ["cron"],

    // 高风险操作前强制人工确认
    "human_confirm":        ["question"],

    // 记忆检索 + 运维事件任务管理
    "memory_planning":      ["memory_search", "memory_get", "task_create",
                             "task_get", "task_update", "task_list"],

    // 跨 Agent 协作（告警分拣→根因分析→变更执行链路）
    "agent_collaboration":  ["sessions_spawn", "sessions_list",
                             "sessions_history", "sessions_send"],

    // 对接外部运维系统（Prometheus/Grafana/PagerDuty/JIRA MCP Server）
    "external_integration": ["mcp_call"],

    // 告警邮件通知（值班人员邮件推送）
    "notification":         ["listen_gmail_reply", "unlisten_gmail"]
  },

  // 明确禁止的工具（运维场景不适用）
  "denied_tools": [
    "product_supplier_search",
    "image_generate",
    "image_edit",
    "see_image",
    "web_search",
    "get_weather",
    "get_location"
  ]
}
```

---

### 3.4 SkillLoader（技能动态加载器）

**职责**：扫描技能目录，解析 `SKILL.md`，动态注入 Agent System Prompt。

**技能目录优先级**（高优先级覆盖）：
```
1. agent-core/skills/<name>/      ← Agent 私有技能（最高优先级）
2. ~/.accio/accounts/<uid>/skills/<name>/  ← 账户级共享技能
```

**SKILL.md 格式约定**（首行 frontmatter）：
```markdown
---
name: gmail-assistant
version: v0.35
description: Send, search, and manage Gmail messages...
trigger: ["发邮件", "搜邮件", "gmail", "email"]
---

# Gmail Assistant

（技能正文，在触发时注入 System Prompt）
```

**动态注入逻辑**：
```python
class SkillLoader:
    def scan_skills(did: str) -> list[SkillMeta]
    def get_system_prompt_injection(did: str, enabled_skills: list[str]) -> str
    def install_skill(did: str, skill_name: str, skill_md: str) -> None
    def uninstall_skill(did: str, skill_name: str) -> None
```

---

### 3.5 SessionManager（会话管理器）

**职责**：单体/群聊会话生命周期管理，历史持久化，@mention 路由。

**会话存储路径**：
```
~/.accio/sessions/<session-id>/
├── meta.json          ← 会话元数据（参与者、创建时间、类型）
└── history.jsonl      ← 消息历史（append-only）
```

**单体会话（Solo Session）**：
```python
# WebSocket 端点
@app.websocket("/api/sessions/{session_id}/chat")
async def solo_chat(ws: WebSocket, session_id: str, agent_id: str):
    await ws.accept()
    async for chunk in agent_vm.stream(session_id, agent_id, prompt):
        await ws.send_text(chunk)
```

**群聊会话（Group Session）**：
- 每条消息广播给所有成员 Agent
- `@{agent_id}` 触发对应 Agent 进入推理回路
- 未被 @mention 的 Agent 收到消息但不响应（写入上下文）
- 消息路由通过 MessageRouter 异步分发

**历史加载与压缩约束**：

- **全量加载**：启动对话时从 `history.jsonl` 读取全部历史，运行时按 `max_tokens` 截断（保留最新 N 条原始消息，超出部分以压缩摘要替换）
- **压缩摘要格式**：压缩结果追加写入 `history.jsonl`，需携带 `"type": "summary"` 标记：
  ```json
  {"type": "summary", "content": "...(压缩摘要)...", "ts": 1743000000000}
  ```
- **session_id 生成**：使用 `uuid4()` 生成，格式为标准 UUID 字符串（不使用 timestamp 或自增 ID）

**MessageRouter（消息总线）**：

对标 Accio `MessageQueue`，Agent 间不直接通信，通过消息总线解耦：
```python
class MessageRouter:
    # 将群聊消息转换为可追踪任务，分发给目标 Agent
    async def route(msg: GroupMessage) -> None:
        for target_did in msg.mentions:
            task = OpsTask(agent_id=target_did, payload=msg)
            await ops_ledger.create(task)
            await agent_vm.trigger(task)
```

---

### 3.6 CronEngine（定时任务引擎）

**职责**：运维定时任务的创建、调度、执行、持久化。对标 Accio Cron 系统。

**实现技术**：APScheduler 3.x（`AsyncIOScheduler`）

**任务存储**：`~/.accio/cron/jobs.json`（与 Accio 原生路径完全对齐）

**调度类型映射**：
```python
# in: 延迟执行（如"5 分钟后发起一次诊断"）
scheduler.add_job(fn, "date", run_date=now + timedelta(ms=job.schedule.inMs))

# at: 指定时间点（如"08:30 生成值班日报"）
scheduler.add_job(fn, "date", run_date=job.schedule.at)

# every: 固定间隔（如"每 5 分钟探测服务存活"）
scheduler.add_job(fn, "interval", seconds=job.schedule.everyMs/1000)

# cron: 标准 cron 表达式（5/6 字段，支持时区）
scheduler.add_job(fn, CronTrigger.from_crontab(job.schedule.expr, timezone=tz))
```

**Payload 执行逻辑**：
```python
async def execute_job(job: CronJob):
    match job.payload.kind:
        case "command":
            # 运维 Shell 命令（df -h / systemctl status / netstat 等）
            result = await tool_registry.dispatch("bash", {"command": job.payload.command})
        case "tool":
            # 调用已注册工具（如 mcp_call 查询 Prometheus）
            result = await tool_registry.dispatch(
                job.payload.tool, job.payload.args
            )
        case "agent":
            # 触发运维 Agent 执行自然语言任务（主要方式）
            result = await agent_vm.run(
                agent_id=job.agent_id,
                prompt=job.payload.message,
                session_id=f"cron-{job.id}-{int(time.time())}"
            )
    # 执行结果写入 OpsLedger 审计
    await ops_ledger.create(OpsTask(
        source="cron", job_id=job.id, result=result
    ))
    # 单次任务完成后自动删除
    if job.deleteAfterRun:
        await cron_engine.remove(job.id)
```

---

### 3.7 OpsLedger（持久化总线）— 继承 v1.1

> 设计不变，详见 v1.1 SDD 2.1 节。

- 独立账本路径：`data/ops-queue/ledger.jsonl`
- 状态机：`pending → running → completed/failed`
- 原子写入：临时文件 + `os.replace` + `fsync`
- 重启恢复：扫描 `running` 状态记录，从 `checkpoint` 续传

---

### 3.8 KnowledgeCore（本地 RAG）— 继承 v1.1

> 设计不变，详见 v1.1 SDD 2.3 节。

- BM25 索引，知识库路径：`data/knowledge/`
- 与 Agent 个人记忆（`data/memory/`）物理隔离
- Markdown H2/H3 分块，支持 `priority_score`

---

### 3.9 ConfigShield（资源锁）— 继承 v1.1

> 设计不变，详见 v1.1 SDD 2.2 节。

- Phase 1：本地文件锁，TTL 30s，心跳 10s，`os.rename` 原子抢占
- Phase 3 升级：跨节点 WebSocket 锁

---

### 3.10 Security Sandbox（执行安全）— 轻量沙箱方案

> **设计原则**：Docker 负责**部署边界**，轻量沙箱负责**任务执行边界**。
> 不做 per-task Docker（启动慢、镜像重、调试复杂），主服务跑在一个 Docker 里，任务执行用 Linux 原生轻量隔离。

#### SandboxProvider 抽象层

```
AgentVM
  → ToolRegistry
      → CommandRunner
          → SandboxProvider
              ├── DirectRunner        # dev / 调试模式（无强隔离）
              ├── NsJailRunner        # 生产默认（nsjail）
              └── BubblewrapRunner    # 兼容 fallback（bwrap）
```

通过 `config/opssentry.yaml`（或环境变量 `SANDBOX_MODE`）切换：
- `sandbox_mode: direct` — 开发调试，只做超时/白名单/日志审计
- `sandbox_mode: nsjail` — 生产默认，OS 级真正隔离
- `sandbox_mode: bwrap` — nsjail 不可用时 fallback

#### 三级 Runner 说明

| Runner | 技术 | 隔离能力 | 适用场景 |
|---|---|---|---|
| **DirectRunner** | subprocess + rlimit | 超时/白名单/审计日志 | 本机开发调试 |
| **NsJailRunner** | nsjail | mount/pid/net namespace + rlimit + cgroup + seccomp | 生产，所有 Bash 工具调用 |
| **BubblewrapRunner** | bwrap | 文件系统只读挂载 + 可见目录白名单 | nsjail 不可用时 |

#### NsJailRunner 默认执行策略（运维场景）

```yaml
max_cpus: 1
rlimit_as: 512m          # 最大虚拟内存
rlimit_nofile: 64        # 最大文件描述符
time_limit: 30s          # 单任务最大执行时长
max_stdout_bytes: 1MB    # stdout 截断上限
max_stderr_bytes: 256KB
network: disabled        # 默认禁网（按工具显式开启）
root: readonly           # 根文件系统只读
writable_mounts:         # 按需挂载可写目录
  - /tmp/opssentry-work
  - /root/.accio/sessions      # 会话历史写回
  - /opt/opssentry/data/ops-queue  # OpsLedger 审计日志写回
env_whitelist:           # 环境变量白名单
  - LANG
  - PATH
  - HOME
run_as_user: nobody      # 禁止以 root 执行
```

#### Seccomp 策略

- **策略文件**：`config/seccomp-default.json`
- **基线来源**：参考 [moby/moby default seccomp profile](https://github.com/moby/moby/blob/master/profiles/seccomp/default.json)，在此基础上剔除危险 syscall
- **必须包含的 Python 运行时 syscall**（否则容器内 Python 进程直接崩）：

```
线程/进程：futex, clone, clone3, set_robust_list, rseq
进程执行：execve, execveat, wait4, waitid
网络：socket, connect, sendto, recvfrom, setsockopt, getsockopt,
      bind, listen, accept4, getpeername, getsockname, shutdown
文件系统：stat, fstat, lstat, poll, getdents64, getcwd, chdir, rename, unlink,
          mkdir, rmdir, chmod, chown, fsync, fdatasync, truncate, ftruncate
内存：mmap2, mremap, madvise, mincore
信号：sigaltstack, kill, tkill, tgkill
时间：nanosleep, clock_nanosleep, gettimeofday, times
其他：getpid, gettid, getuid, getgid, getppid, uname, sysinfo, prctl
```

- **禁止的危险 syscall**：`ptrace`、`mount`、`reboot`、`kexec_load`、`unshare`（除 NsJailRunner 自身使用外）

#### Policy 审计（`config/policy-default.jsonl`）

格式见 3.3 节。沙箱 + Policy 双层防护：沙箱负责 OS 级隔离，Policy 负责命令语义级拦截，两者互补。

#### 审计日志闭环

所有沙箱执行结果（exitCode / stdout 摘要 / stderr / 执行时长）统一写回 OpsLedger：
```json
{
  "type": "sandbox_exec",
  "sandbox_mode": "nsjail",
  "command": "df -h /var",
  "exit_code": 0,
  "duration_ms": 342,
  "stdout_truncated": false,
  "ts": 1743000000000
}
```

> ⚠️ **`seccomp-default.json` 最小 syscall 白名单要求**：
> 当前基线（22 个 syscall）仅覆盖基本 I/O，**不足以运行 Python 3.12 进程**。
> 进入 Docker 测试前必须补全以下 syscall，否则容器内 Python 进程会被 Seccomp 直接阻断：
>
> ```
> 线程/进程：futex, clone, clone3, set_robust_list, rseq
> 进程执行：execve, execveat, wait4, waitid
> 网络（LiteLLM 需要）：socket, connect, sendto, recvfrom, setsockopt, getsockopt,
>                       bind, listen, accept4, getpeername, getsockname, shutdown
> 文件系统：stat, fstat, lstat, poll, getdents64, getcwd, chdir, rename, unlink,
>           mkdir, rmdir, chmod, chown, fsync, fdatasync, truncate, ftruncate
> 内存：mmap2, mremap, madvise, mincore
> 信号：sigaltstack, kill, tkill, tgkill
> 时间：nanosleep, clock_nanosleep, gettimeofday, times
> 其他：getpid, gettid, getuid, getgid, getppid, uname, sysinfo, prctl
> ```
>
> 建议 Phase 2 Docker 测试前参考 [docker/default seccomp profile](https://github.com/moby/moby/blob/master/profiles/seccomp/default.json) 作为白名单基线，再从中剔除危险 syscall（`ptrace`、`mount`、`reboot`、`kexec_load` 等）。

---

## 4. API 设计

### 4.1 REST API 总览

```
# 智能体管理
POST   /api/agents                          ← 创建智能体
GET    /api/agents                          ← 列表
GET    /api/agents/{did}                    ← 获取详情
PATCH  /api/agents/{did}                    ← 更新配置（名称/模型/风格）
DELETE /api/agents/{did}                    ← 删除

# 核心文件
GET    /api/agents/{did}/files/{filename}   ← 读取 SOUL.md 等
PUT    /api/agents/{did}/files/{filename}   ← 写入

# 工具配置
GET    /api/agents/{did}/tools              ← 获取工具组配置
PATCH  /api/agents/{did}/tools              ← 更新启用/禁用

# 技能管理
GET    /api/agents/{did}/skills             ← 列出已绑定技能
POST   /api/agents/{did}/skills/{name}      ← 绑定技能
DELETE /api/agents/{did}/skills/{name}      ← 解绑

# 技能库
GET    /api/skills                          ← 全局技能列表
POST   /api/skills                          ← 创建/上传新技能
GET    /api/skills/{name}                   ← 技能详情
DELETE /api/skills/{name}                   ← 删除技能

# 定时任务
GET    /api/cron/jobs                       ← 列表
POST   /api/cron/jobs                       ← 创建
GET    /api/cron/jobs/{id}                  ← 详情
PATCH  /api/cron/jobs/{id}                  ← 更新（启用/禁用/修改）
DELETE /api/cron/jobs/{id}                  ← 删除
POST   /api/cron/jobs/{id}/run              ← 立即触发

# 会话
POST   /api/sessions                        ← 创建会话（solo/group）
GET    /api/sessions/{id}                   ← 会话详情与历史
DELETE /api/sessions/{id}                   ← 删除会话

# OpsLedger（运维账本）
GET    /api/ops/ledger                      ← 查询账本记录
GET    /api/ops/ledger/recoverable          ← 可恢复任务列表
```

### 4.2 WebSocket 接口

```
# 单体 Agent 流式对话
WS  /api/sessions/{session_id}/chat?agent_id={did}

# 群聊多 Agent 协作
WS  /api/sessions/group/{group_id}/chat
```

**消息格式**（客户端 → 服务端）：
```json
{
  "type": "message",
  "content": "生产环境 nginx 响应变慢，P99 延迟从 200ms 升到 2s，帮我排查",
  "mentions": ["DID-告警分拣器"]
}
```

**消息格式**（服务端 → 客户端，流式）：
```json
{"type": "chunk",      "agent_id": "DID-告警分拣器", "content": "收到，判断为 P1 告警，"}
{"type": "chunk",      "agent_id": "DID-告警分拣器", "content": "正在转交根因分析师..."}
{"type": "tool_call",  "agent_id": "DID-根因分析师",  "tool": "bash",     "args": {"command": "tail -n 500 /var/log/nginx/error.log"}}
{"type": "tool_result","agent_id": "DID-根因分析师",  "result": "upstream timed out (110)..."}
{"type": "tool_call",  "agent_id": "DID-根因分析师",  "tool": "mcp_call", "args": {"name": "query_prometheus", "arguments": {"query": "rate(http_requests_total[5m])"}}}
{"type": "tool_result","agent_id": "DID-根因分析师",  "result": "{\"status\": \"success\", ...}"}
{"type": "chunk",      "agent_id": "DID-根因分析师",  "content": "根因：上游服务连接池耗尽，建议扩容或限流"}
{"type": "done",       "agent_id": "DID-根因分析师"}
```

---

## 5. 数据目录结构

```
Docker Volume: /root/.accio/
├── accounts/
│   └── <uid>/
│       ├── agents/
│       │   └── <did>/
│       │       └── agent-core/
│       │           ├── SOUL.md
│       │           ├── IDENTITY.md
│       │           ├── AGENTS.md
│       │           ├── MEMORY.md
│       │           ├── USER.md
│       │           ├── agent_config.json
│       │           ├── tool-registry.jsonc
│       │           └── skills/
│       │               └── <skill-name>/
│       │                   └── SKILL.md
│       └── skills/                        ← 账户级共享技能
│           └── <skill-name>/
│               └── SKILL.md
├── cron/
│   ├── jobs.json                          ← 定时任务持久化
│   └── runs/                             ← 任务执行日志
│       └── <job-id>.jsonl
└── sessions/
    └── <session-id>/
        ├── meta.json
        └── history.jsonl

项目工作区:
OpsSentry/
├── data/
│   ├── ops-queue/
│   │   ├── ledger.jsonl
│   │   └── sync-buffer.jsonl
│   ├── locks/
│   ├── knowledge/
│   └── memory/
├── config/
│   ├── seccomp-default.json
│   └── policy-default.jsonl
└── src/
    ├── main.py
    ├── agent_manager.py
    ├── agent_vm.py
    ├── tool_registry.py
    ├── sandbox.py             ← 轻量沙箱 SandboxProvider（Phase 2 新增）
    ├── skill_loader.py
    ├── session_manager.py
    ├── cron_engine.py
    ├── message_router.py
    ├── ops_ledger.py          ← Phase 1 已实现
    ├── knowledge_core.py      ← Phase 1 已实现
    ├── config_shield.py       ← Phase 1 已实现
    ├── global_sync.py         ← Phase 1 骨架已实现
    └── routers/
        ├── agents.py
        ├── sessions.py
        ├── cron.py
        └── skills.py
```

---

## 6. 技术栈

| 层 | 技术选型 | 说明 |
|---|---|---|
| Web 框架 | **FastAPI** | 异步、自动生成 OpenAPI 文档 |
| LLM 接入 | **LiteLLM** | 统一多 Provider 接口（Claude/OpenAI/Qwen/Moonshot 等） |
| 定时任务 | **APScheduler 3.x** | `AsyncIOScheduler`，支持 cron/interval/date/in |
| 本地 RAG | **rank-bm25** | Runbook/故障知识库 BM25，纯 Python 零依赖，离线可用 |
| 数据校验 | **Pydantic v2** | 配置模型、API 请求/响应校验 |
| 异步 I/O | **aiofiles** | 非阻塞文件读写 |
| 容器化 | **Docker + docker-compose** | 单命令部署，Volume 挂载持久化 |
| Python 版本 | **3.12** | |
| 外部系统集成 | **MCP Call** | 对接 Prometheus/Grafana/PagerDuty/JIRA MCP Server |
| 安全沙箱 | **nsjail / bwrap / subprocess（SandboxProvider）** | 生产默认 NsJailRunner（nsjail namespace + Seccomp）；fallback BubblewrapRunner；dev DirectRunner；Policy 审计三层防护 |

---

## 7. 实现阶段规划（v2.0）

| 阶段 | 模块 | 依赖 | 状态 |
|---|---|---|---|
| **Phase 1** | OpsLedger / KnowledgeCore / ConfigShield / SyncBuffer | 无 | ✅ 已完成 |
| **Phase 2** | AgentManager + AgentVM + ToolRegistry + Dockerfile | Phase 1 | 🔄 开发中 |
| **Phase 2** | SessionManager（单体对话） | AgentVM | 🔄 开发中 |
| **Phase 3** | SkillLoader + CronEngine + MessageRouter | Phase 2 | ⏳ Pending |
| **Phase 3** | 群聊 GroupSession | MessageRouter | ⏳ Pending |
| **Phase 4** | GlobalSync WebSocket + ConfigShield 分布式升级 | Phase 3 | ⏳ Pending |
| **Phase 4** | 消息渠道（飞书/钉钉/Telegram） | Phase 3 | ⏳ Pending |
