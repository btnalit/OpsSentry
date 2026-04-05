# Change Auditor Skill

## Description
对运维变更进行合规性审查，防止误删或危险操作。

## Tools
- `audit-diff-check`: 审查配置 diff。
- `audit-policy-verify`: 验证操作是否符合 policy-default.jsonl。
- `audit-risk-score`: 评估变更风险等级。

## Triggers
- "帮我审一下这个变更"
- "执行操作前进行风险评估"
- "合规审计"
- "变更风险检查"

## Logic
1. 深度解析指令。
2. 命中高危正则则拦截（L3 拦截）。
3. 要求 TL 二次确认。
