# Phase 2 环境与设计审计报告 (Audit Report)

**审计日期**：2026-03-31
**审计员**：QA Auditor (代码审计与测试专家)
**审计状态**：[部分通过 / 待修正]

---

## 1. 详细设计审计：[SandboxProvider_Design.md](docs/SandboxProvider_Design.md)

### ✅ 通过项
- **架构解耦**：三级 Runner（Direct/NsJail/Bwrap）设计完美适配开发、CI 和生产环境。
- **审计闭环**：`SandboxResult.to_audit_record()` 确保了所有 Shell 执行都有据可查，符合安全基线。
- **Policy 优先级**：明确了 L1(deny) > L2(allow) > L3(approval) 的评估顺序，消除了逻辑歧义。

### ⚠️ 风险点 (待 Developer 实现时注意)
- **[中危] Windows 信号模拟**：`DirectRunner` 在 Windows 下无法使用 `SIGTERM/SIGKILL`。Developer 已补齐 `test_runner.ps1`，但在 `src/sandbox.py` 实现中必须显式处理 `os.name == 'nt'` 的情况，直接调用 `proc.kill()`。
- **[低危] 路径注入**：`writable_mounts` 虽然限制了目录，但 `workdir` 参数若未校验，可能导致在沙箱内跳出预期路径（虽然 NsJail 有 mount 隔离，但 DirectRunner 无保护）。建议对 `workdir` 进行 `os.path.abspath` 与白名单校验。

---

## 2. 环境配置审计：[pyproject.toml](pyproject.toml)

### ✅ 通过项
- **依赖版本控制**：使用了语义化版本区间（如 `>=0.115,<1`），兼顾了稳定性与自动补丁。
- **模块导出**：`tool.setuptools` 配置正确，`src` 目录映射符合 Python 最佳实践。

### ❌ 漏洞/缺失项
- **[高危] `litellm` 安全边界**：`litellm` 默认会缓存 API Keys 或通过环境变量读取。在多租户/多 Agent 环境下，需确保 `AgentVM` 实例化时隔离环境变量，防止 A Agent 窃取 B Agent 的 Key。
- **[低危] 缺失 `types-aiofiles`**：由于使用了 `aiofiles`，建议在 `dev` 依赖中增加类型提示支持。

---

## 3. CI/CD 审计：[.github/workflows/build-image.yml](.github/workflows/build-image.yml)

### ✅ 通过项
- **测试先行**：`build` 任务依赖 `tests` 任务，确保了受损代码不会进入镜像。
- **权限最小化**：`GITHUB_TOKEN` 仅授予 `packages: write`，符合权限最小化原则。

### ⚠️ 优化建议
- **容器安全扫描**：建议增加 `trivy` 或 `anchore` 步骤，在构建完成后扫描镜像漏洞。

---

## 4. 测试驱动审计：[scripts/test_runner.ps1](scripts/test_runner.ps1)

### ✅ 通过项
- **环境隔离**：自动创建 `.venv` 并安装 `-e '.[dev]'`，保证了测试环境的纯净。
- **跨平台适配**：成功解决了 Windows 开发机无法执行 `.sh` 的痛点。

---

## 5. 总结

**审计结论：PASS (Conditional)**。
环境与设计基线已达标，Developer 可继续推进 Task #3。QA 将重点在 `tests/test_phase2.py` 中对 `AgentManager` 的文件权限与路径遍历攻击进行针对性测试。
