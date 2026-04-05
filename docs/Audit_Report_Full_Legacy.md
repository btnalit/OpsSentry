# OpsSentry Phase 2 & 3 核心代码全量审计报告 (Audit_Report_Full.md)

**审计日期**: 2026-04-04
**审计范围**: `src/agent_manager.py`, `src/sandbox.py`, `src/tool_registry.py`, `src/main.py`, `src/agent_vm.py`, `src/ops_ledger.py`
**审计结论**: **驳回 (FAIL)**。发现多处高危沙箱绕过风险及逻辑漏洞，需修复后重新集成。

---

## 1. 高危漏洞清单 (Critical/High)

### [漏洞等级: 高] [src/tool_registry.py:41-48] L1 审计链正则过滤不严
- **触发条件**: 使用变体命令绕过正则，如 `rm -rf  /` (双空格), `rm -rf /./`, `RM -RF /` (大小写), 或使用 `rm -rf /etc/../`。
- **原因分析**: `GLOBAL_DENY_PATTERNS` 采用的正则过于死板，且未开启 `re.IGNORECASE`。攻击者可轻易构造等价命令绕过。
- **修复方案**: 使用更健壮的正则，或在审计前对命令进行规范化（Normalization）。建议增加对常用危险命令及其变体的覆盖。

### [漏洞等级: 高] [src/tool_registry.py:159] L3 路径审批绕过风险
- **触发条件**: 使用 `cd /etc/nginx && cat nginx.conf` 或 `cat "/etc/nginx/nginx.conf"` 绕过 `path in command` 检查。
- **原因分析**: 简单的子字符串匹配无法处理相对路径、符号链接或 shell 转义。
- **修复方案**: 在执行前解析命令中的文件路径，并使用 `Path.resolve()` 进行规范化后再与审批列表对比。

### [漏洞等级: 中] [src/sandbox.py:100, 248, 320] Shell 注入与提权风险
- **触发条件**: 由于所有 Runner 最终都通过 `sh -c` 或 `create_subprocess_shell` 执行，如果传入的 `command` 包含未过滤的管道、分号或反引号，可能导致非预期执行。
- **原因分析**: 虽然工具设计初衷就是执行 Shell 命令，但缺乏对执行环境的最小权限控制（如 NsJail 未指定独立的 rootfs）。
- **修复方案**: 
    1. 为 `NsJailRunner` 和 `BubblewrapRunner` 提供最小化镜像/rootfs，而不是直接挂载宿主机 `/`。
    2. 严格限制 NsJail 的 `writable_mounts`，防止 Agent 修改关键配置文件。

---

## 2. 逻辑与健壮性问题 (Medium/Low)

### [漏洞等级: 中] [src/agent_vm.py:162-186] Prompt 注入风险
- **触发条件**: 在 `MEMORY.md` 或 `USER.md` 中注入特定的 Prompt 指令（如 `Ignore previous instructions`）。
- **原因分析**: `_assemble_system_prompt` 简单拼接 Markdown 内容，缺乏结构化隔离。
- **修复方案**: 为拼接的各部分内容增加明确的 XML 或自定义边界符（例如 `<CORE_FILE name="SOUL.md">...</CORE_FILE>`），并在 System Prompt 中告知模型 these 部分是外部输入。

### [漏洞等级: 低] [src/main.py:20] CORS 策略过宽
- **触发条件**: 任意站点可通过浏览器跨域访问 API。
- **原因分析**: `allow_origins=["*"]` 存在安全隐患。
- **修复方案**: 将 `allow_origins` 限制为预期的管理端域名或本地环回地址。

### [漏洞等级: 低] [src/ops_ledger.py:108-126] Ledger 性能隐患
- **触发条件**: 当审计日志行数达到数万行后，每次 `_persist` 都会重写整个文件。
- **原因分析**: O(N) 写操作在并发高时会成为瓶颈。
- **修复方案**: 改为追加模式（Append-only），并定期进行压缩。

---

## 3. 审查清单核对

- [x] 目录生成权限安全性: **PASS** (通过 `os.makedirs` 默认权限处理)
- [x] 文件原子写入并发安全性: **PASS** (通过 `tempfile` + `os.replace` + `os.fsync` 实现)
- [x] Markdown 核心文件读写边界: **PASS** (由 `AgentManager` 统一管控)
- [x] 技能绑定逻辑兼容性: **PASS** (目前的 Skill 占位逻辑逻辑正确)
- [!] 沙箱隔离性: **FAIL** (默认挂载 `/` 风险极高)
- [!] 审计链绕过: **FAIL** (L1/L3 过滤逻辑过于薄弱)

---

## 4. 修复建议总述

1. **加固审计链**: 弃用简单的字符串匹配，引入命令解析器（如 `shlex`）提取操作目标。
2. **深度隔离**: 为 `NsJailRunner` 配置文件增加独立的 `rootfs` 路径，禁止直接挂载宿主机根目录。
3. **结构化 Prompt**: 优化 `AgentVM` 的 Prompt 构建逻辑，防止注入攻击。

**QA Auditor 签名**: 🕵️‍♂️ (QA Auditor)
