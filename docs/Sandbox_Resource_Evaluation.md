# Sandbox Resource Evaluation & Connection Pooling Design (v1.0)

> **Evaluator**: Architect (系统架构师)
> **Date**: 2026-04-04
> **Status**: Evaluation Complete / Implementation Recommended

## 1. 现状评估 (Current State Evaluation)

经审计 `src/sandbox.py` 源码发现，目前的 `SandboxProvider` 及其具体实现（`DirectRunner`, `NsJailRunner`, `BubblewrapRunner`）在执行 `execute()` 时直接调用 `asyncio.create_subprocess_*`。

**核心瓶颈分析：**
1. **进程膨胀 (Process Proliferation)**：在高并发场景下（如 10+ Agent 同时执行运维巡检），系统会瞬间产生大量子进程。对于 `nsjail` 等重量级沙箱，这会导致 CPU 上下文切换频繁，甚至触及系统的 `nproc` (最大进程数) 或内存 OOM 阈值。
2. **审计 IO 阻塞**：由于每个沙箱执行后都会触发 `OpsLedger` 的物理落盘，过高的并发会导致 `LockedSyncBuffer` 的锁竞争加剧，使原本毫秒级的命令执行变成秒级等待。
3. **缺乏反压机制 (Backpressure)**：目前的架构没有任何手段阻止 Agent 过快地提交任务，一旦积压，会导致整个 API 响应变慢。

## 2. 设计方案：受限执行池 (Bounded Execution Pool)

为了保证系统在极端负载下的稳定性，建议引入 **Semaphore (信号量)** 控制的连接池模式。

### 2.1 架构调整：`BoundedSandboxProvider` 包装器

不直接修改各个 Runner 的底层逻辑，而是通过一个装饰器或包装器类来管理并发数。

```python
class BoundedSandboxProvider(SandboxProvider):
    """
    带并发限制的沙箱执行器包装器。
    """
    def __init__(self, base_provider: SandboxProvider, max_concurrency: int = 10):
        self._inner = base_provider
        # 使用 asyncio.Semaphore 实现全局执行限制
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(self, command: str, **kwargs) -> SandboxResult:
        async with self._semaphore:
            # 只有获取到信号量（“连接”）的请求才能进入沙箱执行
            return await self._inner.execute(command, **kwargs)

    def mode_name(self) -> str:
        return f"{self._inner.mode_name()} (bounded)"
```

### 2.2 核心参数建议 (Recommended Pool Sizes)

- **Default (Workstation)**: `MAX_CONCURRENCY = 8`
- **Production (Server)**: `MAX_CONCURRENCY = 20`
- **Sandbox Timeout**: 保持 `30s` 默认超时，防止死锁进程长时间占用池坑位。

## 3. 资源监控建议 (Monitoring Strategy)

在 Phase 5 的压力测试（#37/47）中，Architect 将重点监控以下指标：
- **Wait Time**: 请求在 Semaphore 上排队的时长。
- **PID Usage**: 实时观测 `ps aux | grep nsjail | wc -l` 是否稳定在限制阈值以下。
- **Memory Pressure**: 观察在高负载下，Swap 分区是否被意外激活。

---

## 4. 后续动作 (Action Plan)

1. **Developer**: 请在 `src/sandbox.py` 中实现 `BoundedSandboxProvider` 并在 `create_sandbox_provider` 工厂函数中默认启用该包装器。
2. **QA Auditor**: 请在 #47 压力测试中，增加对“进程上限”的破坏性测试，验证信号量是否能有效阻止系统崩溃。

**[架构结论]**: 现有的 Sandbox 层必须引入连接池（Semaphore）机制，以确保 OpsSentry 的底层执行引擎在“巡检风暴”中保持刚性稳定。
