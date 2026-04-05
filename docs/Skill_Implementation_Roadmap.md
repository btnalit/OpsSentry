# OpsSentry 运维技能触发冲突对照表 (Trigger Matrix)

为确保 `SkillLoader` 能够精准匹配并加载技能，现将首批 8 个内置技能的触发词进行矩阵化定义，防止语义重叠。

| 技能 ID (Folder Name) | 唯一触发关键词 (Triggers) | 排除/竞态词 (Exclude/Conflicts) |
| :--- | :--- | :--- |
| `disk_cleaner` | `磁盘空间`, `清理`, `df -h`, `日志轮转` | 与 `resource_profiler` 共享 `df` 语义时，优先由 `disk_cleaner` 执行清理。 |
| `service_monitor` | `服务状态`, `nginx`, `mysql`, `systemctl` | 与 `process_watchdog` 区分：`service_monitor` 侧重系统服务管理。 |
| `log_analyzer` | `查日志`, `报错`, `error`, `exception` | 与 `resource_profiler` 区分：侧重非结构化文本分析。 |
| `cert_checker` | `证书`, `ssl`, `过期`, `https` | 严防与 `network_probe` 混淆（Probe 仅检测链路，不校验内容）。 |
| `network_probe` | `网络延迟`, `ping`, `curl`, `丢包` | - |
| `process_watchdog` | `守护进程`, `进程监控`, `ps aux` | 与 `service_monitor` 区分：侧重孤立进程及存活监控。 |
| `resource_profiler` | `资源占用`, `负载`, `cpu`, `ram` | 侧重系统级 Metrics 汇总。 |
| `config_checker` | `配置对比`, `一致性`, `diff` | - |

## 给 Developer 的实现指南 (Implementation Rules)

1. **目录结构**：请在 `skills/` 下为每个技能创建独立目录（如 `skills/disk_cleaner/SKILL.md`）。
2. **XML 实体**：在 `SKILL.md` 正文中，涉及 `rm`、`kill` 等破坏性动作时，必须明确写出：`请先调用 question 工具获取用户授权`。
3. **Cron 映射**：在 `src/cron_engine.py` 中，请实现一个映射表，允许 `CronJob` 直接通过技能 ID 引用对应的 `SKILL.md` 指令集。

---

## 架构审查点 (Architectural Guardrails)

- [ ] **语义去重**：如果同一输入触发了 2 个以上技能，`SkillLoader` 必须按“最长前缀匹配”或“优先级权重”进行过滤。
- [ ] **Token 预算**：每个 `SKILL.md` 的正文内容建议控制在 500 Tokens 以内。
