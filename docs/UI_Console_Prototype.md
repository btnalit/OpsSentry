# OpsSentry 控制台可视化原型设计方案 (v1.0)

## 1. 设计哲学 (Design Philosophy)
OpsSentry 控制台定位于“硬核运维中枢”。拒绝平庸的业务管理界面，采用 **高密度、暗色调、低延迟** 的视觉风格，模拟专业终端环境。

- **视觉风格**: Cyberpunk Terminal (赛博终端)
- **配色方案**: 
  - 背景: `Obsidian Black (#0D0D0D)`
  - 主色: `Matrix Green (#00FF41)` - 用于正常状态、成功日志
  - 辅助色: `Electric Blue (#00A3FF)` - 用于 Agent 身份信息、链接
  - 警告色: `Alert Amber (#FFB000)` - 用于警告、挂起任务
  - 致命色: `Crimson Red (#FF0000)` - 用于审计阻断、沙箱报错
- **字体规范**: `Fira Code` 或 `JetBrains Mono` (等宽字体，支持 Ligatures)

## 2. 页面布局架构 (Layout Architecture)

采用三栏响应式布局，确保在不同尺寸屏幕下维持信息密度。

### 2.1 左侧边栏：Agent 舰队概览 (Fleet Overview)
- **功能**: 展示所有已注册的 Agent 列表。
- **UI 元素**: 
  - `DID` (缩略显示) + `Name`
  - `Vibe` 标签 (用不同颜色区分：expert/friendly 等)
  - 实时状态指示灯 (绿色呼吸灯表示运行中，红色闪烁表示被审计拦截)
  - 搜索/过滤栏：支持按 UID 或 技能名称过滤。

### 2.2 中央区域：核心指令舱 (Command Deck)
- **顶部状态栏 (HUD)**: 
  - 当前 Agent 资源占用情况 (虚拟指标)
  - 活跃技能 (Active Skill)
  - 最后一次审计通过的命令。
- **中心日志流 (Streaming Terminal)**: 
  - **核心特性**: 实时滚动，支持通过 WebSocket (`/api/sessions/chat`) 注入日志。
  - **交互**: 鼠标悬停日志条目可显示该动作在 `OpsLedger` 中的完整 JSON。
  - **输入框**: 底部一个高亮光标的输入行，支持快捷键调用 Agent 命令。
- **底部状态条**: 显示 API 延迟 (ms) 和 后端服务连接状态。

### 2.3 右侧边栏：审计与灵魂监测 (Audit & Soul Inspector)
- **标签页 1: Soul**: 实时预览 `SOUL.md` 和 `IDENTITY.md`。
- **标签页 2: Ledger**: 展示最近 5 条审计记录。
  - 提供 `Rollback` 按钮，一键触发 `OpsLedger` 的恢复逻辑。
- **标签页 3: Skills**: 动态扫描出的可用技能列表，支持开关切换。

## 3. 核心交互逻辑 (Core Interactions)

1. **流式反馈**: 当 Agent 调用工具（如 `bash`）时，中央终端不仅显示输出结果，还要显示“沙箱启动中...”、“L1 审计通过...”、“命令执行中...”等中间状态过程，增强掌控感。
2. **审计阻断视觉化**: 当 `ToolRegistry` 阻断命令时，终端背景应瞬间出现红色脉冲视觉效果，并弹出一个非模态的审计报告摘要，指出具体的危险操作。
3. **像素级打回机制 (The "Master" Review)**: 任何偏离 `SOUL` 定义的交互行为，UI 都会以紫色高亮标注，提醒运维人员。

## 4. 技术实现建议 (Tech Stack)
- **Framework**: `Next.js 14` (App Router)
- **Styling**: `Tailwind CSS` + `Framer Motion` (用于终端滚动和状态灯动画)
- **State Management**: `Zustand` (轻量化状态管理)
- **Icons**: `Lucide React`
- **Charts**: `Recharts` (用于展示 Agent 执行频率曲线)

## 5. 待评审清单 (Review Checklist)
- [ ] 响应式适配：在 14 寸笔记本屏幕下，三栏布局是否过于拥挤？
- [ ] 可读性：`Matrix Green` 在黑色背景下的对比度是否符合无障碍标准？
- [ ] 延迟显示：WebSocket 丢失重连时的 UI 表现是否平滑？

---
**[阶段状态: 完成]**
**[实体文件路径: DOCS/UI_Console_Prototype.md]**
**[设计人: Frontend Master]**
