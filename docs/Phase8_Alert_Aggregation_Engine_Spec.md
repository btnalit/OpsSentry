# Phase 8: Multi-dimensional Alert Aggregation Engine Design (#72)

## 1. Background
In a large-scale distributed cluster, a single failure (e.g., node downtime or network glitch) can trigger a cascade of error logs and status changes across multiple nodes and agents. Sending an individual notification for each event would lead to an **Alert Storm**, overwhelming the O&M personnel and hiding the root cause.

The goal of the **Alert Aggregation Engine** is to collect, group, and merge these events into a single, summarized notification.

## 2. Core Components

### 2.1 Alert Event Structure
A unified structure for all alerts:
```python
{
    "id": str,          # Unique alert ID
    "type": str,        # NODE_DEAD, TASK_FAILED, CRON_ERROR, etc.
    "severity": str,    # CRITICAL, WARNING, INFO
    "source": str,      # node_id or agent_id
    "message": str,     # Short description
    "details": dict,    # Full error context, stack trace, etc.
    "timestamp": int,   # UTC ms
}
```

### 2.2 Aggregation Rules
Alerts will be aggregated over a **time window** (default: 60s) based on:
1. **Source Deduplication**: Identical alert type from the same source within the window.
2. **Type Grouping**: Multiple alerts of the same type across different sources (e.g., "3 nodes are DEAD").
3. **Task Merging**: For a failed task, only the final failure state is reported, not intermediate retry errors.

### 2.3 Storage (Alert Buffer)
- **Redis (Cluster Mode)**: Use a Redis List or Stream (`sentry:alerts:buffer`) to buffer raw alerts across nodes.
- **In-Memory (Standalone)**: Use a Python `Queue` for small deployments.

## 3. Workflow (The "Alert Pulse")

1. **Emission**: Components like `AgentManager` (on failover) or `OpsLedger` (on `mark_failed`) emit a raw alert to the buffer.
2. **Buffering**: The `AlertAggregator` collects events over a configurable window (e.g., 60s).
3. **Aggregation Logic**:
    - If it's a `NODE_DEAD` event: Group all dead nodes into one "Node Loss Alert".
    - If it's a `TASK_FAILED` event: Group by `agent_id` or `task_name`.
4. **Dispatching**:
    - Construct a summarized `OutboundMessage`.
    - Send via `FeishuChannel` or `DingTalkChannel` (configured via `ConfigShield`).
    - Also push to the Cyber-terminal HUD via WebSocket.

## 4. Proposed Implementation: `src/cluster/alert_engine.py`

- `AlertEvent`: Pydantic model for validation.
- `AlertAggregator`: Background thread/task that manages the buffer and aggregation loop.
- `AlertRule`: Rule-based logic for merging.

## 5. Security & Resilience
- **HMAC Signing**: All alerts dispatched to external channels must be signed as per Admission Spec.
- **Fail-safe**: If the aggregation engine itself crashes, raw alerts are persisted in the Redis buffer to be picked up after restart.

## 6. Next Steps
- Implement the `AlertAggregator` core.
- Add hooks in `AgentManager.perform_failover` and `OpsLedger.mark_failed`.
- Add a dedicated "Alerts" tab to the Frontend HUD (Phase 8 UI extension).
