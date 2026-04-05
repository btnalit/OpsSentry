# OpsSentry Project Heartbeat & Recovery Architectural Spec (v1.0)

针对董事长提出的“15 分钟心跳唤醒”机制，从系统架构角度评估，该方案是实现**高可用研发流水线**的关键。为确保心跳触发后能瞬间对齐架构设计并恢复上下文，特制定本规范。

## 1. 架构评估：Watchdog 模式 (Watchdog Pattern)

该机制本质上是一个“看门狗计时器”。
- **可行性**：极高。通过外部 Cron 触发 `Tech Lead` 的 `AgentVM` 实例，可以强制刷新内存上下文（Context Hydration）。
- **核心挑战**：如何避免“由于上下文丢失导致的逻辑断层”或“重复执行已完成的任务”。

## 2. 心跳对齐协议 (Heartbeat Alignment Protocol)

每当 Tech Lead 被心跳唤醒时，必须执行以下 **“三位一体”对齐自检**：

1.  **物理状态对齐 (Physical State Sync)**：
    - 读取 `Dev_Status_Board.md`（当前实时进度）。
    - 读取 `TASKS.md`（长期路线图）。
    - **逻辑**：对比两者差异，若 Board 中的阶段与 TASKS 不符，立即以 TASKS 为准进行修正。
2.  **设计基线对齐 (Design Baseline Sync)**：
    - 读取 `DOCS/SDD_OpsSentry.md`（技术设计文档）。
    - **逻辑**：验证当前正在开发的模块（如 `AgentVM` 或 `CronEngine`）是否偏离了架构初衷（如：是否漏掉了 XML 转义，是否漏掉了权限校验）。
3.  **内存上下文恢复 (Memory Rehydration)**：
    - 读取 `${agent_core}/MEMORY.md`。
    - **逻辑**：提取最近 3 次决策记录，恢复对“董事长偏好”和“技术债修复”的记忆。

## 3. 容错与原子性 (Fault Tolerance)

为了支持“无损重连”，所有开发任务必须具备**幂等性 (Idempotency)**：
- **Developer**：在编码前先检查目标文件是否存在及版本号，避免重复覆盖。
- **QA Auditor**：审计报告应包含 `File_Hash`，确保心跳重连后，审计的是同一份代码。

## 4. 架构师建议 (Architect's Recommendation)

建议 Tech Lead 在 `Dev_Status_Board.md` 中增加一个 `[Heartbeat_Checkpoint]` 字段。
- **内容**：记录最后一次成功完成的 `Step_ID` 和对应的 `Design_Version`。
- **作用**：心跳唤醒后，直接跳转至该 Checkpoint，消除“我是谁，我在哪，我要做什么”的迷茫期。

---

**[结论]**：
该机制在架构上完全可行，且能显著提升系统的稳健性。建议立即将上述“对齐逻辑”固化到各智能体的 System Prompt 中。
