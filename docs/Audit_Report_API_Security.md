# OpsSentry Phase 4 API 安全审计报告 (Audit_Report_API_Security.md)

**审计日期**: 2026-04-04
**审计范围**: `src/main.py`, `src/routers/`, `src/agent_manager.py`
**审计结论**: **有条件通过 (CONDITIONAL PASS)**。系统在代码实现层面（如路径脱敏）做得很好，但在 API 架构层面（如鉴权）处于空白状态。

---

## 1. 核心安全漏洞分析 (Critical/High)

### [漏洞修复: 通过] Cron 任务 IDOR 漏洞加固 (#32)
- **验证结果**: **通过 (PASS)**。
- **确认点**: `src/routers/cron.py` 已在所有 CRUD 及立即执行接口中强制引入了 `uid` 所有权校验逻辑。POC 测试证明非所有者 `uid` 无法删除或访问他人任务。

### [漏洞修复: 通过] Agents 核心文件 IDOR 漏洞加固 (#33)
- **验证结果**: **通过 (PASS)**。
- **确认点**: `src/routers/agents.py` 的全量接口已引入 `Depends(verify_user_id)` 校验及 `Header(X-User-ID)` 强制对比。
- **POC 验证**: 使用 `user_a` 的 `X-User-ID` 请求头尝试读取 `user_b` 的 `SOUL.md` 已被 403 拦截。自动化回归测试 `tests/test_api_security_idor.py` 全量通过。

### [安全基线建议] 生产环境鉴权升级
- **现状**: 目前采用 `X-User-ID` 请求头进行简单比对，适用于开发阶段和受控内网。
- **风险**: 请求头可伪造。
- **建议方案**: 在正式生产交付前，必须在 `verify_user_id` 中集成真正的 JWT 或 OAuth2 校验。

### [漏洞等级: 高] Cron 任务恶意注入
- **漏洞点**: `/api/cron/jobs/` (POST)
- **触发条件**: 攻击者可以为任意 `uid` 创建 `kind: "command"` 的定时任务。
- **原因分析**: `CronEngine` 信任 API 传入的 `uid`。由于缺乏鉴权，这允许越权执行系统命令。
- **修复建议**: 严格校验创建任务的 `uid` 必须与当前登录用户一致。

---

## 2. 纵深防御验证 (Defense-in-Depth)

### [审计结论: 优] 路径穿越 (Path Traversal) 防御
- **验证结论**: **通过 (PASS)**。
- **核查点**: 
    - `AgentManager._validate_core_filename` 采用了白名单机制，限制仅能读取 `CORE_FILE_NAMES` 内的文件。
    - `_normalize_did` 显式拦截了 `..` 和路径分隔符。
    - 物理存储层级结构合理，由 `AgentManager` 统一管控。

### [审计结论: 警示] CORS 策略过宽
- **漏洞点**: `src/main.py:43`
- **风险**: `allow_origins=["*"]` 允许任何站点通过浏览器跨域访问 API。虽然对于本地开发很方便，但在生产环境下会暴露 API 接口。
- **修复建议**: 在生产环境下配置显式的域名白名单。

---

## 3. 审计建议清单

1.  **[优先级: 紧急]**: 在 `src/dependencies.py` 中实现统一的鉴权拦截器。
2.  **[优先级: 高]**: 修正 `CronEngine` 的 API 路由，增加权属校验。
3.  **[优先级: 中]**: 收缩 CORS 策略。

**QA Auditor 签名**: 🕵️‍♂️ (QA Auditor)
