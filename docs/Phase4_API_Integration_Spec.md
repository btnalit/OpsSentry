# OpsSentry Phase 4 API Integration & Coordination Spec

本文件定义了 Phase 4 前端控制台与后端核心服务（VM, Cron, Skills）的联调规范，并明确了 **Cron-to-Skill** 的参数传递标准。

## 1. 全局 API 概览 (Frontend-to-Backend)

| 模块 | 基础路径 | 核心功能 | 实时性要求 |
| :--- | :--- | :--- | :--- |
| **Agent 管理** | `/api/agents` | CRUD, 技能绑定, 核心文件读写 | 低 |
| **审计流水** | `/api/ops/ledger` | 历史审计查询, 任务溯源 | 中 |
| **定时任务** | `/api/cron/jobs` | 自动化巡检配置, 立即触发 | 中 |
| **实时终端** | `/api/sessions/chat` | WebSocket 双向流式推理与交互 | **极高** |

---

## 2. Cron-to-Skill 参数传递规范 (Parameter Passing Spec)

为了让定时任务能精准且参数化地触发运维技能，建议采用以下标准格式。

### 2.1 自然语言触发 (Standard Agent Payload)
这是最通用的方式，利用 `AgentVM` 的 `SkillLoader` 进行语义匹配。
- **Payload 示例**:
  ```json
  {
    "kind": "agent",
    "message": "执行磁盘清理，清理路径为 /var/log，保持 80% 阈值。"
  }
  ```
- **工作流**: Cron 触发 -> `AgentVM` 加载 `disk_cleaner` 技能 -> Agent 解析 `message` 中的参数 -> 调用工具执行。

### 2.2 结构化强制触发 (Future-proof Payload)
对于需要 100% 确定性的巡检任务，建议在 `Payload.args` 中显式指定 `skill_id`。
- **建议格式**:
  ```json
  {
    "kind": "agent",
    "message": "[AUTO_TRIGGER] skill_id: disk_cleaner, target: /var/log, threshold: 80%"
  }
  ```
- **VM 处理逻辑**: `AgentVM` 识别 `[AUTO_TRIGGER]` 前缀后，跳过通用语义检索，强制加载 `disk_cleaner` 的 `SKILL.md`，并将后续键值对作为上下文注入。

---

## 3. 前端联调关键点 (Terminal Interaction)

### 3.1 WebSocket 消息格式
前端控制台应支持以下三种消息类型的渲染：
1.  **`type: "thought"`**: 渲染为灰色斜体或折叠块，展示 Agent 的推理过程（Thought）。
2.  **`type: "call"`**: 渲染为高亮工具图标（如 🛠️），展示正在调用的工具名及参数。
3.  **`type: "observation"`**: 渲染为终端输出流，展示工具执行结果。
4.  **`type: "message"`**: 最终回复，渲染为正常的对话气泡。

### 3.2 审计阻断反馈 (Audit Pulse)
当 `ToolRegistry` 拦截命令时，后端将通过 WebSocket 发送特殊状态：
- **JSON**: `{ "type": "error", "error_code": "AUDIT_REJECTED", "detail": "L1 Rule: rm -rf / is forbidden" }`
- **前端动作**: 触发 UI 上的“红色脉冲”视觉效果。

---

## 4. 安全红线要求 (Security Checkpoints)

1.  **权属校验**: 在 `/api/cron/jobs` 的所有增删改查路由中，前端必须传递 `X-User-ID`，后端通过 `src/routers/cron.py` 校验该任务是否属于该用户。
2.  **转义防护**: 前端控制台在展示 `MEMORY.md` 等核心文件时，必须防止 XSS 攻击，后端已完成 XML 转义，前端需确保其作为纯文本渲染。
3.  **敏感操作阻断**: 凡是涉及 `config_checker` 修改或 `service_monitor` 重启的操作，前端必须弹窗提示用户确认。

---

## 5. 验收标准 (Acceptance Criteria)

- [ ] 前端 Terminal 能实时展示 `df -h` 的动态执行过程。
- [ ] 成功创建一个每 5 分钟运行一次的 `log_analyzer` 任务，并能在 Ledger 中看到记录。
- [ ] 模拟输入 `rm -rf /`，前端能正确显示红色审计警告。
