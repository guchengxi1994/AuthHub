# AuthHub

AuthHub 是一个独立的企业级认证与 RBAC 授权基础框架。它只负责用户、组织、角色、权限、动态模块、Token/Session 和审计，不承载具体业务模块，也不托管业务数据库或 Redis 的生命周期。

当前交付的是框架核心与可选 FastAPI HTTP 适配器；Python SDK 应在服务端 API 稳定后基于这些契约单独发布。

## 架构边界

```text
业务服务 / FastAPI / SDK
             │ HTTP（可替换适配器）
             ▼
      AuthHub API Adapter
             │
      AuthHub Application（认证、RBAC、模块注册、缓存失效、审计）
             │ 依赖注入端口
      Repository / Cache / TokenService / PasswordHasher / AuditLog
             │
       宿主提供的 SQL 数据库、Redis、密钥服务
```

`src/auth_hub/domain` 没有任何 Web、ORM 或 Redis 依赖；`src/auth_hub/ports` 是基础设施适配器需要实现的接口；`infrastructure.py` 提供两种兜底/接入方式：本地 SQLite 持久化数据库、内存 Cache，以及可接收宿主 `redis-py` 客户端的 `RedisCache`。框架使用这些连接，但不创建、部署或关闭宿主的数据库/Redis 服务。

## 授权模型

AuthHub 的可视化配置以一条明确的 RBAC 链路组织：

```text
业务模块 -> 资源 -> 权限 -> 角色 -> 用户 / 组织
```

- **业务模块**：上游业务的边界，例如“订单中心”或“MCP 管理”。它是归属和隔离单位，不是前端页面或组件。
- **资源**：需要授权的业务对象，并且必须属于一个业务模块。可选类型为 `api`（API 接口）、`entity`（业务实体/集合）、`mcp_server`、`mcp_tool`、`page`（页面/菜单）和 `custom`。页面/菜单只是资源的一种，不能把“前端模块”或“页面组件”泛化为全部资源。
- **权限**：对一个资源执行的动作。页面/菜单只能使用 `view`/`manage`，MCP Tool 只能使用 `view`/`execute`/`manage`，API 和业务实体可以使用 `read`、`create`、`update`、`delete` 等动作。权限的资源、模块和操作由服务端校验，不能只依赖管理端下拉框。
- **角色**：权限集合；用户通过角色获得权限。用户也可关联一个或多个组织，用于组织归属和后续数据范围策略扩展。

管理端创建模块、角色和权限时不要求填写技术 ID 或编码，系统会自动生成。Python SDK 和上游服务仍可提交显式模块 ID、角色编码或权限编码，以便进行幂等同步和程序化鉴权。

## 快速启动

核心包零运行时依赖，默认 `AuthHub.local()` 使用 SQLite 文件和内存缓存，可直接开发和测试：

```bash
pip install -e .

# 默认创建 authhub.db；也可以传入 :memory: 之外的 SQLite 文件路径
AUTH_HUB_DATABASE=./var/authhub.db uvicorn auth_hub.main:app --reload
```

启用 FastAPI 接口：

```bash
pip install -e '.[web]'
uvicorn auth_hub.main:app --reload
```

默认初始化一个系统级 `admin` 用户，开发密码由 `AuthHubSettings(admin_password=...)` 指定；本地缺少外部数据库时使用 SQLite，缺少 Redis 时使用内存缓存。生产环境应将宿主提供的 SQLAlchemy/其他数据库 Repository、RedisCache、生产密码哈希器和 TokenService 注入 `AuthHub(...)`。

## Docker Compose

```bash
cp .env.example .env
# Set AUTH_HUB_ADMIN_PASSWORD in .env
docker compose up --build
```

服务地址为 `http://localhost:8000`，可通过 `AUTH_HUB_PORT` 覆盖端口。Compose 会启动 AuthHub 和 Redis；AuthHub 使用 Redis 保存权限缓存和可撤销的 opaque Token/Session，使用具名卷中的 SQLite 文件保存 AuthHub 自身的用户、RBAC、模块和审计数据。停止容器不会删除数据；需要清空本地环境时执行 `docker compose down -v`。

管理端在 `http://localhost:8000/admin`，首次登录使用 `.env` 中的管理员用户名和密码。

管理端前端位于 `src/auth_hub/web/`：`templates/admin.html` 是页面结构，`static/admin.css` 是管理端样式，`static/admin.js` 是 API 交互逻辑。FastAPI 仅将它们作为 `/admin` 和 `/admin/assets/*` 提供，Python 后端不内嵌前端代码。构建 wheel 时会一并包含这些资源。

这是一个可零配置启动的开发/单机部署组合。生产环境应将 `AuthHub(...)` 注入宿主提供的 PostgreSQL/MySQL Repository、Redis 客户端和密钥服务；不会由 AuthHub 创建、部署或关闭这些外部基础设施。

## 当前 API

- `POST /api/auth/login`：用户名密码登录并签发 Token
- `POST /api/auth/refresh`、`POST /api/auth/logout`
- `GET /api/auth/me`、`POST /api/auth/check-token`
- `POST /api/auth/check`、`POST /api/auth/check/batch`
- `GET /api/auth/user-permissions`
- `POST /api/modules/register`：幂等保存业务模块及权限元数据
- `POST /api/resources`、`DELETE /api/resources/{resource_id}`：管理模块下的受控资源
- `POST /api/permissions`：创建资源操作权限，并可同时授予角色

鉴权失败统一返回 `code`，包括 `UNAUTHENTICATED`、`TOKEN_INVALID`、`USER_DISABLED`、`PERMISSION_DENIED` 等。

## 数据库与 Redis 接入

数据库和 Redis 是“由宿主提供、由框架接入”，不是“框架完全不使用”。

```python
from auth_hub import AuthHub, AuthHubSettings, RedisCache

# repository 使用宿主已有 SQLAlchemy session/连接实现 AuthHubRepository。
repository = MySqlAuthHubRepository(session_factory)
redis_cache = RedisCache(redis_client, namespace="my-service:authhub:")
hub = AuthHub(repository, redis_cache, token_service, password_hasher, audit_log, AuthHubSettings())
```

如果宿主没有 Redis，可以先使用 `InMemoryCache()`；如果没有数据库连接，可以使用 `AuthHub.local("./authhub.db")`，它会用 SQLite 持久化 AuthHub 自己的数据。两种 fallback 都是为了开发、测试和单机部署，生产环境仍建议使用宿主的数据库和 Redis。

框架不会创建或部署外部基础设施，也不会关闭宿主传入的数据库连接池或 Redis 客户端。

## 后续阶段

1. 完成 SQLAlchemy/PostgreSQL/MySQL 仓储适配器和 Redis 缓存适配器（仍由宿主传入连接）。
2. 固化 OpenAPI/错误码/Token 响应契约。
3. 固化管理端的 OpenAPI/静态资源发布和端到端测试。
4. API 稳定后再制作 `auth-hub-client` Python SDK，并以版本化契约测试保证兼容性。
