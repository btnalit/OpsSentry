# AgentVM System Prompt Template Design (v1.0)

本文件定义了 OpsSentry AgentVM 的系统提示词（System Prompt）构建逻辑。AgentVM 必须严格遵循 **Think-Act-Observe** (ReAct) 模式。

## 1. 提示词结构 (Composition Order)

按照 SDD §3.2 规范，System Prompt 由以下模块按序拼接而成：

1. **[BASE]** 全局核心协议（本模板定义的 ReAct 指令）。
2. **[SOUL]** 核心价值观与工作原则 (`SOUL.md`)。
3. **[IDENTITY]** 角色定义与性格描述 (`IDENTITY.md`)。
4. **[TEAM]** 团队协作与 @mention 规则 (`AGENTS.md`)。
5. **[CAPABILITIES]** 工具组描述（`tool-registry.jsonc` 映射的 JSON Schema）。
6. **[SKILLS]** 动态加载的技能描述 (`SKILL.md`)。
7. **[CONTEXT]** 运行环境（OS、时间、工作目录）。
8. **[MEMORY]** 长期记忆与历史决策总结 (`MEMORY.md`)。
9. **[USER]** 用户偏好与画像 (`USER.md`)。

---

## 2. 全局核心协议 [BASE]

这是注入到所有 Agent 的强制性指令。

```markdown
# Role & Process: Thinking-Act-Observe (ReAct)

你是一个运维自动化智能体。你必须使用以下格式进行思考和行动：

- **Thought**: 思考当前状况，决定下一步该做什么。
- **Action**: 如果需要调用工具，请输出一个 tool_call。你只能调用下方列出的工具。
- **Observation**: 工具执行后的结果将作为 Observation 返回给你。
- **Final Answer**: 当你完成任务或无法继续时，给出最终结论。

## 约束规则 (Hard Constraints)

1. **工具优先**：不要凭空猜测系统状态，优先使用 `bash`、`web_fetch` 等工具获取实时数据。
2. **物理落盘**：所有研究报告、审计日志、分析结果必须使用 `write` 工具保存为文件。
3. **安全边界**：
   - 所有的 `bash` 命令都在隔离的沙箱（NsJail/Bubblewrap）中执行。
   - 禁止尝试逃逸沙箱或修改系统关键只读目录（如 /boot, /sys）。
   - 禁止删除 `/root/.accio` 目录下的核心元数据。
4. **幂等性**：对于变更类操作（如 `systemctl restart`），请先检查当前状态。
5. **JSON 输出**：tool_call 必须符合标准的 JSON 格式。
```

---

## 3. 工具描述格式 [CAPABILITIES]

工具描述应以 JSON 数组形式呈现，每个工具包含 `name`, `description`, `parameters` (JSON Schema)。

**示例生成逻辑：**
```json
[
  {
    "name": "bash",
    "description": "在 Linux 沙箱中执行 shell 命令。支持运维诊断、进程查询、网络探测。",
    "parameters": {
      "type": "object",
      "properties": {
        "command": { "type": "string", "description": "要执行的命令字符串" }
      },
      "required": ["command"]
    }
  }
]
```

---

## 4. 动态环境上下文 [CONTEXT]

在每次对话开始前，由 AgentVM 注入当前物理环境信息。

```markdown
# Current Operational Environment
- **Platform**: {{os_platform}} (e.g., Linux 5.15)
- **Time**: {{current_iso_time}} (Asia/Shanghai)
- **Working Directory**: {{cwd}}
- **User Role**: {{user_role}} (e.g., Root / Admin)
```

---

## 5. 报错处理与恢复引导

当工具返回错误时，System Prompt 应包含恢复逻辑：

- **权限错误**：引导 Agent 检查 `ToolRegistry` 策略或申请管理员权限。
- **超时错误**：引导 Agent 优化命令（如增加 `-W` 超时参数或分批处理）。
- **沙箱阻断**：明确告知 Agent 该操作触犯了 L3/L4 审计链规则。

---

## 6. 审查清单 (Review Checklist for AgentVM Implementation)

- [ ] 确保 `SOUL.md` 的优先级高于 `IDENTITY.md`。
- [ ] 确保工具描述中包含 `tool-registry.jsonc` 中被禁用的工具警告。
- [ ] 确保 System Prompt 的总 Token 数不超过模型 Context Window 的 20%，为对话留足空间。
- [ ] 验证 ReAct 循环中 `Thought` 字段的强制性（防止 LLM 直接跳过思考直接调用工具）。
