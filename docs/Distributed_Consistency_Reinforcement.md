# Distributed Consistency Reinforcement Design (Task #41)

> **Document**: [DOCS/Distributed_Consistency_Reinforcement.md](DOCS/Distributed_Consistency_Reinforcement.md)
> **Author**: Architect (系统架构师)
> **Date**: 2026-04-04
> **Status**: Draft for Implementation

## 1. Objective
Ensure absolute data consistency and atomicity for `SyncBuffer` operations (Append, Read, Clear) in a high-concurrency, multi-node environment. This reinforcement leverages the distributed locking capabilities of `ConfigShield` to prevent race conditions and data corruption.

## 2. Problem Statement
Current `SyncBuffer.append` uses `open("a")` with `os.fsync()`. While this ensures that individual lines are written to disk, it does not provide:
1. **Multi-process atomicity**: Multiple processes appending simultaneously might lead to interleaved or corrupted JSONL lines if the OS buffer management fails or during high-pressure scenarios.
2. **Read-Modify-Write Safety**: Operations like `clear()` or future "rotate" operations need a global lock to prevent data loss during the transition.
3. **Node-level Coordination**: In a distributed setup, nodes need a shared lock manager to synchronize access to the central sync-buffer.

## 3. Architecture: Locked Sync Pattern

We will introduce a `LockedSyncBuffer` (or an enhanced `SyncBuffer`) that integrates `ConfigShield`.

### 3.1 Distributed Lock Mapping
The lock resource path for a sync-buffer will be derived from its absolute file path.
- **Resource Identifier**: `sync_buffer:{absolute_path}`
- **Lock Manager**: `ConfigShield` instance.

### 3.2 Enhanced Append Flow (ReAct Pattern)

1. **Acquire Lock**: Call `ConfigShield.acquire(resource_path)`.
2. **Execute Operation**: Perform `SyncBuffer.append()`.
3. **Release Lock**: Call `ConfigShield.release(resource_path)`.

### 3.3 Proposed Implementation Structure

```python
class LockedSyncBuffer:
    def __init__(self, buffer: SyncBuffer, shield: ConfigShield):
        self.buffer = buffer
        self.shield = shield
        # Resource path for the lock
        self.resource_id = f"sync_buffer:{self.buffer.buffer_path.absolute()}"

    def append_safe(self, envelope: SyncEnvelope):
        # E2E Closed Loop with ConfigShield
        self.shield.acquire(self.resource_id)
        try:
            self.buffer.append(envelope)
        finally:
            self.shield.release(self.resource_id)

    def read_all_safe(self) -> list[dict]:
        self.shield.acquire(self.resource_id)
        try:
            return self.buffer.read_all()
        finally:
            self.shield.release(self.resource_id)

    def clear_safe(self):
        self.shield.acquire(self.resource_id)
        try:
            self.buffer.clear()
        finally:
            self.shield.release(self.resource_id)
```

## 4. E2E Closed Loop Integration

### 4.1 Dependency Injection
The `SyncBuffer` factory in `src/dependencies.py` should be updated to return a `LockedSyncBuffer` that shares the global `ConfigShield` instance.

### 4.2 Error Handling & Resilience
- **Lock Timeout**: If `ConfigShield` cannot acquire the lock within a certain period, the operation should retry with exponential backoff or fail with a `SyncLockTimeout` error.
- **Stale Lock Recovery**: `ConfigShield`'s built-in TTL logic ensures that if a node crashes while holding the lock, other nodes can reclaim it after the timeout.

## 5. Verification Plan
- **Concurrency Test**: Spawn 10 processes using `LockedSyncBuffer` to write 1000 messages each. Verify that exactly 10,000 valid JSON lines exist in the buffer.
- **Race Condition Test**: Attempt to `clear()` while multiple `append()` operations are in progress. Verify no data corruption.
- **Lock Heartbeat Test**: Verify that long-running operations (if any) are protected by the `ConfigShield` heartbeat mechanism.

---

**Architect's Note**: This design completes the bridge between Phase 4 (Security & Networking) and Phase 5 (Multi-Agent Hub). By locking the sync-buffer, we ensure that the Hub's "Single Source of Truth" remains consistent across the entire OpsSentry cluster.
