# Phase 6: LedgerStorage Specification (v1.0)

## 1. 目标 (Objectives)
将 `OpsLedger` 的存储层从当前的 $O(N^2)$ 全量写 JSONL 模式重构为基于 **SQLite (WAL Mode)** 的增量存储模式。
通过定义 `ILedgerStorage` 抽象接口，实现存储引擎的可插拔性，并确保与 `ConfigShield` 分布式锁机制的协同稳定性。

## 2. 核心架构 (Core Architecture)

### 2.1 抽象接口 `ILedgerStorage`
定义底层存储操作的原子方法：

```python
from abc import ABC, abstractmethod
from typing import Any, List, Optional
from .ledger_entry import LedgerEntry # 假设 LedgerEntry 被提取到独立模块

class ILedgerStorage(ABC):
    @abstractmethod
    def append(self, entry: LedgerEntry) -> None:
        """持久化一个新分录 (O(1))"""
        pass

    @abstractmethod
    def update(self, entry_id: str, **updates: Any) -> LedgerEntry:
        """更新指定分录的字段并返回最新状态"""
        pass

    @abstractmethod
    def get(self, entry_id: str) -> Optional[LedgerEntry]:
        """根据 ID 获取分录"""
        pass

    @abstractmethod
    def list_all(self, status: Optional[str] = None, limit: int = 1000) -> List[LedgerEntry]:
        """按时间降序排列的分录列表"""
        pass

    @abstractmethod
    def delete(self, entry_id: str) -> None:
        """逻辑删除或物理删除分录"""
        pass

    @abstractmethod
    def count(self) -> int:
        """获取总分录数"""
        pass
```

### 2.2 SQLite 实现策略 (`SQLiteLedgerStorage`)
*   **模式选择**: 启用 `WAL (Write-Ahead Logging)`。
    *   `PRAGMA journal_mode=WAL;`
    *   `PRAGMA synchronous=NORMAL;`
*   **并发处理**: 设置 `busy_timeout` 为 5000ms。
*   **表结构**:
    | 字段 | 类型 | 说明 |
    | :--- | :--- | :--- |
    | id | TEXT (PK) | UUID 或自定义 ID |
    | action | TEXT | 动作名称 |
    | status | TEXT | 状态 (pending/running/completed/failed) |
    | checkpoint | TEXT (JSON) | 执行断点数据 |
    | created_at | INTEGER | 毫秒级时间戳 (索引) |
    | updated_at | INTEGER | 毫秒级时间戳 |
    | accio_ref | TEXT | Accio Task 引用 (索引) |
    | metadata | TEXT (JSON) | 扩展元数据 |
    | last_error | TEXT | 最近错误信息 |

## 3. 与 ConfigShield 的协同机制

### 3.1 锁定策略变更
*   **旧模式**: `OpsLedger` 调用 `ConfigShield` 对 `ledger.jsonl` 进行排他锁定，以防止全量重写时的竞态。
*   **新模式**: 
    1.  **底层一致性**: 依赖 SQLite 内部的消息/页级锁定机制（WAL 模式下允许多读一写）。
    2.  **逻辑一致性**: `OpsLedger` **不再强制** 在所有读写操作前调用 `ConfigShield`。
    3.  **互斥任务**: 对于需要保证“同一时刻只有一个 Agent 处理特定任务”的场景，仍由 `AgentVM` 调用 `ConfigShield` 锁定 **任务资源 ID**，而非锁定 **数据库文件**。

### 3.2 性能预期
*   **写入性能**: 从 $O(N)$ 降至 $O(1)$。
*   **内存占用**: 废除“内存全量加载”模式，采用流式查询。

## 4. 迁移路径 (Migration Path)
1.  **Dual-Mode Support**: 在 `src/ops_ledger.py` 中保留 `OpsLedger` 类，但其构造函数接受 `storage: ILedgerStorage`。
2.  **Legacy Importer**: 实现一个一次性迁移脚本，将 `ledger.jsonl` 数据导入 SQLite。
3.  **Hot-Swap**: 通过配置项切换 `storage` 实现类。
