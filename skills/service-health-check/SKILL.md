# Service Health Check Skill

## Description
对 HTTP/TCP 服务进行状态探测，支持自定义 URL、端口和超时。

## Tools
- `http-probe`: HTTP(S) GET/POST 探测。
- `tcp-ping`: 端口连通性检查。
- `dns-lookup`: 检查域名解析是否正常。

## Triggers
- "检查 [URL] 的健康状态"
- "服务 [端口] 通了吗"
- "巡检 API"
- "探测连通性"

## Logic
1. 校验 URL/IP 合法性。
2. 调用 `sandbox` 执行 `curl` 或 `nc`。
3. 记录探测耗时及返回码。
