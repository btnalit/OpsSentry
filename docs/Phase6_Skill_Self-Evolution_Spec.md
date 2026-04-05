# Phase 6: Skill Self-Evolution & Runbook Auto-Generation Spec (v1.0)

## 1. 目标 (Objectives)
实现 OpsSentry 的“自主演进”能力：通过分析 `OpsLedger` 中的历史成功自愈案例，自动生成结构化的运维 Runbook，并将其注入 `KnowledgeCore` (RAG)，使系统在面对类似故障时具备更精准的执行逻辑和更快的响应速度。

## 2. 核心架构与流程 (Core Architecture & Flow)

### 2.1 数据闭环 (Data Loop)
```mermaid
graph TD
    A[OpsLedger (SQLite)] -- 1. 提取成功路径 --> B[EvolutionManager]
    B -- 2. 模式识别与摘要 --> C[Runbook Generator (LLM)]
    C -- 3. 生成 Markdown Runbook --> D[Knowledge Base (data/knowledge/)]
    D -- 4. 索引重建 --> E[KnowledgeCore (RAG)]
    E -- 5. 增强推理 --> F[AgentVM]
    F -- 6. 执行并产生新日志 --> A
```

### 2.2 演进逻辑
1.  **提取 (Extraction)**: 定期轮询 `OpsLedger` 中 `status='completed'` 且带有丰富 `checkpoint` 数据的分录。
2.  **蒸馏 (Distillation)**: 过滤掉琐碎任务，聚焦于复杂的自愈流程（如：磁盘满处理、内存泄漏重启、证书自动更新等）。
3.  **生成 (Generation)**: 使用特定的 Prompt 模板，将 `action`, `checkpoint` (步骤序列), `metadata` 转换为标准 Markdown Runbook。
4.  **注入 (Injection)**: 存入 `data/knowledge/evolved/` 目录。

## 3. RAG 召回精度保障 (RAG Accuracy & Maintenance)

为了防止自动生成的知识库“产生幻觉”或“过度膨胀”导致召回精度下降，采取以下策略：

### 3.1 优先级权重 (Priority Scoring)
*   **Manual (手动录入)**: `priority_score = 1.0` (默认最高权重)。
*   **Auto-Generated (自动生成)**: 初始 `priority_score = 0.5`。
*   **Verified (实战验证)**: 如果 Agent 引用该 Runbook 且任务成功，分数 +0.1；如果失败，分数 -0.2。

### 3.2 去重与合并 (Deduplication)
*   在生成新 Runbook 前，调用 `KnowledgeCore.search()`。
*   如果召回的 Top 1 **BM25 分值超过置信度阈值（如 > 15.0）且 Action 匹配**，则不创建新文件，而是将新案例的差异点“补丁式”合并到现有 Runbook 的 `## Case Studies` 章节中。
*   注：BM25 分值是非归一化的，不可直接使用 0.85 这种相似度百分比。

### 3.3 语义隔离 (Semantic Isolation)
*   Runbook 必须包含固定的元数据块，标明其来源分录 ID。
*   在 `AgentVM` 的 System Prompt 中增加指令，告知其优先参考 `Manual` 类型的 Runbook，将 `Auto` 类型视为“参考案例”。

## 4. 与 KnowledgeCore 的集成定义

`EvolutionManager` 将通过以下方式与 `KnowledgeCore` 交互：

```python
class EvolutionManager:
    def __init__(self, ledger: OpsLedger, knowledge: KnowledgeCore):
        self.ledger = ledger
        self.knowledge = knowledge

    async def evolve_step(self):
        # 1. 从 SQLite 提取高价值分录
        entries = self.ledger.list_entries(status="completed", limit=100)
        
        for entry in entries:
            # 2. 评估是否需要生成 Runbook
            if self._should_generate(entry):
                runbook_md = await self._generate_runbook(entry)
                
                # 3. 写入物理文件
                filename = f"evolved_{entry.id}.md"
                write_file(f"data/knowledge/evolved/{filename}", runbook_md)
                
        # 4. 触发 RAG 索引重建
        self.knowledge.rebuild_index()
```

## 5. 风险与规避 (Risks & Mitigation)
*   **风险**: 错误的自愈路径被固化为 Runbook。
    *   **规避**: 强制要求 Runbook 必须通过 QA Auditor 的“回溯审计”脚本（校验分录的 `last_error` 是否为空，且 `updated_at` 是否合理）。
*   **风险**: 存储空间浪费。
    *   **规避**: 设置 `evolved/` 目录的最大配额，采用 LRU 或“低分淘汰”机制清理长期未被引用的自动生成文档。
