# Log Analyzer Skill

## Description
分析日志文件中的异常，对 ERROR 和 WARN 级别进行聚类并提供排查建议。

## Tools
- `log-scanner`: 扫描指定路径或 stdout。
- `log-cluster`: 对日志进行聚类，识别重复错误。
- `log-severity-count`: 统计各级别日志数量。

## Triggers
- "日志里有异常吗"
- "帮我查一下最近 1 小时的 ERROR 日志"
- "聚类分析日志"
- "分析 [服务名] 的日志异常"

## Logic
1. 使用 `grep -E "ERROR|WARN|FATAL"` 提取。
2. 对相似报错通过 `edit_distance` 进行合并。
3. 结合 `KnowledgeCore` 匹配历史解决方案。
