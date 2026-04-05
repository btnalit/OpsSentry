# Cert Expiry Checker Skill

## Description
扫描域名 SSL 证书有效期，并在到期前 N 天发出告警。

## Tools
- `cert-info-get`: 获取证书详细信息。
- `cert-batch-scan`: 批量扫描域名列表。

## Triggers
- "证书快过期了吗"
- "查一下 [域名] 的 SSL 有效期"
- "证书巡检"
- "即将到期的证书"

## Logic
1. 调用 `openssl s_client`。
2. 解析 `notAfter` 字段。
3. 比较当前时间，计算剩余天数。
