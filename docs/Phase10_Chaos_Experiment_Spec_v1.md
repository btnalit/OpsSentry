# Phase 10: #101 全链路混沌实验故障模拟清单 (v1.0)

作为 OpsSentry 军团的最终实战演练，本方案旨在模拟真实生产环境中的极端故障场景，验证系统在“生存边界”的韧性与确定性。

## 1. 实验目标 (Objectives)
*   **自愈确定性**：验证在机房级故障下，任务 Failover 的成功率与执行唯一性（无脑裂执行）。
*   **数据完整性**：审计在 I/O 异常与协调器崩溃时，OpsLedger 的事务一致性。
*   **视觉感知对齐**：验证 HUD 2.0 在极端抖动下的状态映射准确度。

## 2. 故障场景清单 (Chaos Scenarios)

### 场景 A：全局网络分区 (Global Network Partition / Brain-Split)
*   **模拟手段**：使用 `tc` 在 50% 的节点间注入 100% 丢包，将集群划分为孤立的两半。
*   **审计要点**：
    1.  **Leader 冲突检测**：验证是否存在两个 Leader 同时下发指令（Split-Brain）。
    2.  **状态同步收敛**：网络恢复后，审计集群是否能在 60s 内自动对齐 `sentry:task:registry`，并清理重叠任务。

### 场景 B：核心协调器崩溃 (Redis Master Crash)
*   **模拟手段**：强杀 `opssentry-redis` 容器，模拟神经中枢瘫痪。
*   **审计要点**：
    1.  **孤岛自守逻辑**：验证节点在失去 Redis 连接时，是否能根据本地 `ConfigShield` 缓存维持现有任务运行，而非集体崩溃。
    2.  **重连雪崩防护**：Redis 恢复后，验证 1000+ 节点并发重连是否会产生瞬时查询风暴压垮数据库。

### 场景 C：节点级联失效 (Cascading Avalanche)
*   **模拟手段**：每隔 5s 随机 `kill` 一个存活节点，持续 1 分钟，直至存活节点负载率突破 90%。
*   **审计要点**：
    1.  **重平衡压力测试**：验证在极高 Failover 频率下，任务能否准确漂移。
    2.  **反压机制激活**：观察 `CronEngine` 是否按优先级（Priority）舍弃低价值任务以保护核心巡检链路。

### 场景 D：存储 I/O 阻塞 (I/O Latency & Write Stalls)
*   **模拟手段**：在 `OpsLedger` (SQLite WAL) 所在的挂载卷注入高延迟 (500ms+ per write)。
*   **审计要点**：
    1.  **事务超时处理**：验证审计流水是否会出现写丢失或死锁。
    2.  **异步缓冲验证**：审计 `AuditShipper` 的本地缓冲区是否能在此期间安全持有日志分片。

### 场景 E：非法心跳攻击 (Impersonation Attack)
*   **模拟手段**：模拟攻击者尝试使用已失效的 Token 或伪造的 HMAC 签名注入大规模恶意心跳包。
*   **审计要点**：
    1.  **拦截准确率**：验证 `validate_heartbeat` 在高并发恶意请求下的过滤效率与 CPU 开销。

---

## 3. 验收标准 (Success Criteria)
*   **RTO (Recovery Time Objective)**：核心任务在节点死亡后 45s 内必须完成重新接管。
*   **Data Integrity**：全量审计流水在故障期间无任何 `UNIQUE constraint failed` 或记录丢失。
*   **Visual Alignment**：HUD 2.0 在所有场景下的报警响应延迟 < 1s。
