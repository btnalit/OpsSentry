# Runbook Retriever Skill

## Description
基于 BM25 算法在 `data/knowledge/` 目录下检索相关的运维手册 (Runbook)。

## Tools
- `runbook-search`: 语义检索手册。
- `runbook-get-content`: 获取指定手册的全文。
- `runbook-list-categories`: 列出所有手册目录。

## Triggers
- "怎么处理 [故障名]"
- "查找关于 [应用名] 的运维文档"
- "如何重启 [服务]"
- "检索 Runbook"

## Logic
1. 关键词提取。
2. 调用 `KnowledgeCore` 检索。
3. 返回 Top 3 结果并摘要。
