# Sentinel 校验规则集 (Sentinel_Rules.json)

本文件定义了 `scripts/Sentinel_Sync.py` 必须遵循的物理校验准则，由 QA Auditor 维护。

## 1. 物理层校验 (L1: Physical Existence)
- **存在性**: 目标文件必须存在于 `TASKS.md` 或 `Dev_Status_Board.md` 声明的路径。
- **非空性**: 文件大小必须 > 100 字节（杜绝只写了 `import` 的占位符）。
- **修改时效**: 文件最后修改时间应晚于该阶段启动时间（防止使用历史旧文件充数）。

## 2. 逻辑层校验 (L2: Logical Integrity)
- **语法合法性**: 所有 `.py` 文件必须能通过 `python -m py_compile` 或 `ast.parse` 校验，严禁提交有语法错误的代码。
- **核心组件检查**:
    - `src/agent_manager.py`: 必须包含 `class AgentManager`。
    - `src/sandbox.py`: 必须包含 `class SandboxProvider`。
    - `src/agent_vm.py`: 必须包含 `class AgentVM`。
    - `src/tool_registry.py`: 必须包含 `class ToolRegistry`。
- **导入一致性**: 检查内部导入路径是否统一使用 `from src.xxx import yyy`，严禁相对导入冲突。

## 3. 看板同步准则 (L3: Board Sync Rules)
- **单向强制同步**: 物理文件存在且 L1/L2 校验通过 -> `TASKS.md` 状态强制改为 `✅ 已完成`。
- **降级预警**: 物理文件缺失或校验失败但 `TASKS.md` 标记为完成 -> 状态降级为 `⚠️ Data_Loss` 或 `🛠️ Rework` 并向 Tech Lead 发送告警。
- **正则表达式安全**: 脚本修改 Markdown 时，必须使用非贪婪匹配，确保不破坏表格结构。

## 4. 安全红线
- **隔离性**: 脚本严禁扫描 `.accio/` 以外或 `.git/` 内部的敏感目录。
- **只读权限**: 对 `src/` 源码仅限读取，严禁任何形式的写入（仅允许修改 `TASKS.md` 和 `Dev_Status_Board.md`）。
