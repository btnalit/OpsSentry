# OpsSentry #34 分布式同步与消息渠道准入测试规格说明书 (Admission Test Spec)

**文档版本**：v1.0 | **最后更新**：2026-04-04
**针对任务**：#34 分布式同步与消息渠道 (Feishu/DingTalk 接入与跨节点数据同步)

---

## 1. 分布式同步审计 (Distributed Sync Audit - `src/global_sync.py`)

### 1.1 并发写入一致性 (Concurrent Write Consistency)
- **测试用例**: 模拟多个节点（进程/线程）同时向 `sync-buffer.jsonl` 追加数据包。
- **准入标准**:
    - 文件内容无数据交叉、无半截行。
    - 每行数据必须为有效的 JSON 格式。
    - 确保 `os.fsync` 被正确调用以保证断电后的数据持久化。

### 1.2 数据包 Schema 强校验 (Schema Strict Validation)
- **测试用例**: 发送缺失 `node_id`、`msg_type` 或 `ts` 的数据包至同步缓冲区。
- **准入标准**:
    - `SyncBuffer` 必须拒绝非法数据，抛出显式的 Schema 异常。
    - 禁止未定义格式的 Payload 进入同步链路。

### 1.3 缓冲区资源保护 (Resource Protection)
- **测试用例**: 持续向缓冲区注入海量小数据包（>10万条）。
- **准入标准**:
    - `read_all` 操作不得导致内存溢出（OOM）。
    - 需实现缓冲区滚动机制或大小限制，防止磁盘空间耗尽导致宿主机崩溃。

---

## 2. 消息渠道安全审计 (Message Channel Security Audit)

### 2.1 凭证硬编码审查 (Credential Hardcoding)
- **测试用例**: 对 Feishu/DingTalk 接入代码进行静态分析。
- **准入标准**:
    - **严禁** 硬编码 `app_id`、`app_secret` 或 `webhook_url`。
    - 所有敏感凭证必须通过 `ConfigShield` 加密存储或从环境变量中动态读取。

### 2.2 客户端流控 (Client-side Rate Limiting)
- **测试用例**: 模拟 Agent 触发报警风暴（如 1 秒内触发 100 次报警）。
- **准入标准**:
    - 必须实现客户端侧的 Token Bucket 或 Leaky Bucket 算法。
    - 达到第三方平台频率限制前，系统应自动进行消息合并或静默，防止被平台封禁。

### 2.3 Webhook 安全性 (Webhook Inbound Security)
- **测试用例**: 伪造 Webhook 请求发送至同步监听端。
- **准入标准**:
    - 必须实现基于 HMAC-SHA256 的签名校验逻辑。
    - 拒绝任何签名缺失或非法的入站请求。

### 2.4 消息内容脱敏与渲染安全 (Content Sanitization)
- **测试用例**: 在发送的消息中注入 Shell 字符、XML 标签或非法 Markdown 语法。
- **准入标准**:
    - 在推送到外部群组前，必须执行强制转义（Escape）。
    - 确保消息在手机端/桌面端渲染时不会触发非预期的格式错误或溢出攻击。

---

## 3. 审计准则 (Veto Power)

任何未通过上述 **2.1 (凭证硬编码)** 或 **2.3 (签名校验)** 的任务交付，将由 QA Auditor 执行**一票否决**，立即打回返工。

**QA Auditor 签名**: 🕵️‍♂️ (QA Auditor)
