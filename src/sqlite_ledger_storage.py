from __future__ import annotations

import json
import sqlite3
import threading
import time
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional, Sequence, TypeVar, Callable

from .ledger_entry import LedgerEntry

T = TypeVar("T")

def with_retry(
    max_attempts: int = 5,
    base_delay: float = 0.01,
    max_delay: float = 0.5
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to implement exponential backoff with jitter for sqlite3 operations.
    Handles 'database is locked' (sqlite3.OperationalError).
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e).lower() and attempts < max_attempts - 1:
                        attempts += 1
                        # Exponential backoff with jitter
                        delay = min(max_delay, base_delay * (2 ** attempts))
                        jitter = delay * 0.1 * (random.random() * 2 - 1)
                        time.sleep(delay + jitter)
                        continue
                    raise
            return func(*args, **kwargs) # Should not be reached but for safety
        return wrapper
    return decorator


class ILedgerStorage(ABC):
    @abstractmethod
    def append(self, entry: LedgerEntry) -> None:
        """持久化一个新分录 (O(1))"""
        pass

    @abstractmethod
    def update(
        self, 
        entry_id: str, 
        updates: dict[str, Any], 
        expected_statuses: Optional[Sequence[str]] = None
    ) -> bool:
        """
        原子更新指定分录的字段。
        如果指定了 expected_statuses，则仅当当前 status 在其中时才执行更新。
        返回是否更新成功 (rowcount > 0)。
        """
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

    @abstractmethod
    def get_incremental(
        self, 
        last_created_at: int, 
        last_id: str, 
        limit: int = 100
    ) -> List[LedgerEntry]:
        """获取增量分录 (用于日志上报)"""
        pass


class SQLiteLedgerStorage(ILedgerStorage):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            # busy_timeout=5000ms per Spec
            # We still wrap it with retry for extra safety against peak jitter
            @with_retry()
            def connect():
                conn = sqlite3.connect(str(self.db_path), timeout=5.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                return conn
            self._local.conn = connect()
        return self._local.conn

    @with_retry()
    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                checkpoint TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                accio_ref TEXT,
                metadata TEXT,
                last_error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_status ON ledger(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_created_at ON ledger(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_accio_ref ON ledger(accio_ref)")
        conn.commit()

    @with_retry()
    def append(self, entry: LedgerEntry) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO ledger (id, action, status, checkpoint, created_at, updated_at, accio_ref, metadata, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.action,
                entry.status,
                json.dumps(entry.checkpoint),
                entry.created_at,
                entry.updated_at,
                entry.accio_ref,
                json.dumps(entry.metadata),
                entry.last_error,
            ),
        )
        conn.commit()

    @with_retry()
    def update(
        self, 
        entry_id: str, 
        updates: dict[str, Any], 
        expected_statuses: Optional[Sequence[str]] = None
    ) -> bool:
        conn = self._get_conn()
        
        fields = []
        values = []
        for key, value in updates.items():
            if key in {"id", "created_at"}: # Immutable
                continue
            fields.append(f"{key} = ?")
            if key in {"checkpoint", "metadata"}:
                values.append(json.dumps(value))
            else:
                values.append(value)
        
        if not fields:
            return True
            
        query = f"UPDATE ledger SET {', '.join(fields)} WHERE id = ?"
        values.append(entry_id)
        
        if expected_statuses:
            placeholders = ", ".join("?" for _ in expected_statuses)
            query += f" AND status IN ({placeholders})"
            values.extend(expected_statuses)
        
        cursor = conn.execute(query, tuple(values))
        conn.commit()
        
        return cursor.rowcount > 0

    @with_retry()
    def get(self, entry_id: str) -> Optional[LedgerEntry]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    @with_retry()
    def list_all(self, status: Optional[str] = None, limit: int = 1000) -> List[LedgerEntry]:
        conn = self._get_conn()
        query = "SELECT * FROM ledger"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        
        cursor = conn.execute(query, tuple(params))
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    @with_retry()
    def delete(self, entry_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM ledger WHERE id = ?", (entry_id,))
        conn.commit()

    @with_retry()
    def count(self) -> int:
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM ledger")
        return cursor.fetchone()[0]

    @with_retry()
    def get_incremental(
        self, 
        last_created_at: int, 
        last_id: str, 
        limit: int = 100
    ) -> List[LedgerEntry]:
        conn = self._get_conn()
        query = """
            SELECT * FROM ledger 
            WHERE created_at > ? OR (created_at = ? AND id > ?) 
            ORDER BY created_at, id ASC 
            LIMIT ?
        """
        cursor = conn.execute(query, (last_created_at, last_created_at, last_id, limit))
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    def _row_to_entry(self, row: sqlite3.Row) -> LedgerEntry:
        d = dict(row)
        d["checkpoint"] = json.loads(d["checkpoint"]) if d["checkpoint"] else {}
        d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else {}
        return LedgerEntry.from_record(d)

    def close(self) -> None:
        """Close the database connection for the current thread."""
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
