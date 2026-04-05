# Incident Reporter Skill

## Description
根据 OpsLedger 历史记录自动生成故障事件报告（Post-mortem）。

## Tools
- `incident-fetch-timeline`: 提取故障期间的操作链。
- `incident-summary-gen`: 生成摘要。
- `incident-export-pdf`: 导出 PDF 报告。

## Triggers
- "生成故障报告"
- "复盘昨晚的告警"
- "事件报告 [ID]"
- "导出 Incident"

## Logic
1. 限定时间窗口。
2. 过滤 `OpsLedger` 中的关键变更。
3. 区分 "Cause" (根因) 和 "Impact" (影响)。
