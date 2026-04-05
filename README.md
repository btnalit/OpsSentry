# OpsSentry (运维哨兵)

[![Status](https://img.shields.io/badge/Status-Industrial%20Release%20Ready-green.svg)](https://github.com/btnalit/OpsSentry)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**OpsSentry** is a production-grade, distributed AI-native O&M (Operations & Maintenance) platform. It features secure isolation, self-healing perception, and multi-agent collaboration capabilities. Designed for high-availability environments, OpsSentry transforms traditional O&M into a resilient, autonomous "Sentry" system.

---

## 🚀 Vision & Key Features

OpsSentry is built on the **R&D Resilience Protocol**, ensuring the system remains operational and self-recovering even under extreme chaos.

-   **AgentVM Core**: Powered by LiteLLM with a "Think-Act-Observe" reasoning loop and automatic context compaction.
-   **Multi-Level Sandboxing**: Integrated protection using **NsJail** and **Bubblewrap** for secure tool execution.
-   **OpsLedger (High Performance)**: A SQLite-based (WAL Mode) audit bus capable of **11,000+ records/s** with atomic state transitions.
-   **Self-Healing Sentinel**: Real-time reconciliation between physical state, tasks, and system integrity.
-   **Distributed Cluster & Failover**: Redis-backed lease arbitration and Gossip-based peer discovery. Supports **RTO < 45s** failover.
-   **Cyberpunk HUD 2.0**: A real-time React-based dashboard with terminal-style visualization, audit pulses, and failover tracking.
-   **Interactive Channels**: Deep integration with **Feishu/Lark** and **Slack** via interactive cards for human-in-the-loop authorization.

---

## 🏗️ Architecture Overview

The system is composed of several critical layers:

1.  **Orchestration Layer**: `AgentVM` handles high-level reasoning and task decomposition.
2.  **Storage Layer**: `OpsLedger` provides an append-only, high-concurrency audit trail with semantic indexing.
3.  **Isolation Layer**: `SandboxProvider` ensures that all O&M operations (scripts, commands) run in a strictly controlled environment.
4.  **Cluster Layer**: `MessageRouter` and `AuditShipper` handle cross-node communication and centralized log aggregation.
5.  **Control Layer**: `FastAPI` REST & WebSocket backend + `React/Vite` Frontend.

---

## 🛠️ Tech Stack

-   **Backend**: Python 3.10+, FastAPI, LiteLLM, APScheduler.
-   **Frontend**: React, Vite, Tailwind CSS, Lucide React.
-   **Storage**: SQLite (WAL Mode), Redis (Streams & PubSub).
-   **Isolation**: Linux Namespaces (NsJail, Bubblewrap).
-   **Deployment**: Docker, Docker Compose (Hardened).

---

## 🚦 Getting Started

### Prerequisites

-   Docker & Docker Compose.
-   Redis 6.2+.
-   Python 3.10+ (for local development).

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/btnalit/OpsSentry.git
    cd OpsSentry
    ```

2.  **Environment Setup**:
    Create a `.env` file based on `.env.example` (template provided in docs).

3.  **Deploy with Docker Compose**:
    ```bash
    docker-compose up -d
    ```

4.  **Access the HUD**:
    Open `http://localhost:3000` to access the Cyberpunk Dashboard.

---

## 🛡️ Security Hardening

OpsSentry is designed for production safety:
-   **Non-Root Execution**: Every component runs as the `opssentry` user.
-   **Resource Constraints**: Strict CPU/Memory limits applied via Docker.
-   **Path Normalization**: Prevents directory traversal attacks in `ToolRegistry`.
-   **HMAC Validation**: All Webhooks and cross-node signals are signed.
-   **RBAC/JWT**: Secure API access with granular role-based controls.

---

## 📚 Documentation

Detailed documentation is available in the `docs/` directory:
-   [OpsSentry Operations Runbook](docs/OpsSentry_Operations_Runbook.md)
-   [System Scaling Guide](docs/OpsSentry_Scaling_Guide.md)
-   [Chaos Experiment Spec](docs/Phase10_Chaos_Experiment_Spec_v1.md)

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

---

**Tech Lead Note**: *This project is a result of a 10-phase disciplined R&D cycle. It is RELEASE READY for industrial deployment.*
