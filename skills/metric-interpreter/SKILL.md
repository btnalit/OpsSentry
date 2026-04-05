# Metric Interpreter Skill

## Description
解读 Prometheus 或监控指标，分析趋势并预警水位。

## Tools
- `metric-query`: 获取指标当前值。
- `metric-trend`: 绘制指标变化趋势。
- `metric-threshold-check`: 检查指标是否超过阈值。

## Triggers
- "现在的 CPU 负载是多少"
- "内存使用率高吗"
- "分析 [指标名] 的趋势"
- "监控报表"

## Logic
1. 接入监控源 (Prometheus API)。
2. 对比历史 Baseline。
3. 生成文字解读报告。
