# Phase 8: Distributed Authentication & RBAC Specification (#70)

## 1. 目标 (Objectives)
构建 OpsSentry 生产级的安全防御体系。通过引入基于 **JWT** 的分布式身份认证与 **RBAC (基于角色的访问控制)**，确保跨节点 API 调用、Agent 指令执行及敏感数据访问均受到严格的权限管控与审计。

## 2. 身份认证架构 (Authentication Architecture)

### 2.1 基于 JWT 的分布式令牌
*   **签发中心**: 集群 Leader 节点（或独立认证服务）负责签发 JWT。
*   **验证机制**: 所有节点共享相同的 `JWT_SECRET`（存储在 `ConfigShield` 中）。
*   **Payload 结构**:
    ```json
    {
      "sub": "user_123",
      "role": "operator",
      "org_id": "org_alpha",
      "exp": 1712217600,
      "iat": 1712214000
    }
    ```

### 2.2 跨节点安全通信 (mTLS / Token-based)
*   **节点身份**: 每一个 Sentry 节点在启动时通过 `CLUSTER_SECRET` 换取一个 `NodeToken`。
*   **API 鉴权**: 内部集群接口（如 `/api/cluster/status`）强制校验 `Authorization: Bearer <NodeToken>`。

## 3. RBAC 模型设计 (RBAC Model)

### 3.1 角色定义 (Roles)
| 角色 | 权限集 | 说明 |
| :--- | :--- | :--- |
| **Admin** | `*` | 全量权限，包括集群管理与密钥轮转 |
| **Operator** | `agent:exec`, `audit:view`, `skill:use` | 运维操作员，负责下发指令与查看结果 |
| **Auditor** | `audit:view` | 只读审计员，仅能查看 OpsLedger 与 HUD |
| **Read-Only** | `status:view` | 基础观察员，仅能查看集群健康度 |

### 3.2 资源级隔离 (Resource Isolation)
*   **X-User-ID 校验**: 所有的资源访问（如获取特定的 `LedgerEntry`）必须验证请求者的 `org_id` 或 `user_id` 与资源归属一致。
*   **命名空间 (Namespace)**: 在 Redis 中引入多租户隔离，任务锁前缀增加 `org_id`。

## 4. 核心组件改动 (Component Impact)

### 4.1 `src/auth.py` (新增)
*   实现 `JWTManager`。
*   集成 FastAPI `Security` 依赖项。

### 4.2 `src/dependencies.py` (更新)
*   新增 `get_current_user` 依赖，自动解析 Header 中的 JWT 并校验权限。

### 4.3 `src/config_shield.py` (更新)
*   增加对 `AUTH_CONFIG` 的加密存储支持。

## 5. 任务分解 (Task Breakdown)
*   **Architect (Myself)**: ✅ 输出规格说明书 (#70)。
*   **Developer**: 🏗️ 实现 `src/auth.py` 及 FastAPI 鉴权中间件 (#70.1)。
*   **Developer**: 🏗️ 将现有的 Agent 执行与审计查询接口接入 RBAC 校验 (#70.2)。
*   **QA Auditor**: 🏗️ 设计 IDOR (平行越权) 与 JWT 伪造测试用例 (#70.3)。

## 6. 验收标准 (Acceptance Criteria)
1.  **JWT 完整性**: 篡改 JWT 签名或过期 Token 必须返回 401。
2.  **权限阻断**: `Auditor` 角色尝试调用 `POST /api/v1/agent/exec` 必须返回 403。
3.  **数据隔离**: 用户 A 无法查询到用户 B 的审计记录。
