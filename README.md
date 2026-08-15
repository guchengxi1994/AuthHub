# AuthHub

AuthHub 是一个独立的企业级认证与 RBAC 授权基础框架。它只负责用户、组织、角色、权限、动态模块、Token/Session 和审计，不承载具体业务模块，也不托管业务数据库或 Redis 的生命周期。

当前交付包含框架核心、可选 FastAPI HTTP 适配器、位于 `sdk/` 的独立 Python 上游服务客户端 `auth-hub-client`，以及位于 `web-sdk/` 的 React 权限渲染包 `@auth-hub/react`。

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

`src/auth_hub/domain` 没有任何 Web、ORM 或 Redis 依赖；`src/auth_hub/ports` 是基础设施适配器需要实现的接口；默认持久化适配器使用 SQLAlchemy Core，数据库 URL 决定 SQLite、PostgreSQL 或 MySQL 方言，并由 `MetaData.create_all()` 初始化 AuthHub 自身的表。Redis 仍由宿主 `redis-py` 客户端接入。框架不会创建、部署或关闭数据库/Redis 服务，也不会创建业务数据表。

## 授权模型

AuthHub 的可视化配置以一条明确的 RBAC 链路组织：

```text
业务模块 -> 资源 -> 权限 -> 角色 -> 用户 / 组织
```

- **业务模块**：上游业务的边界，例如“订单中心”或“MCP 管理”。它是归属和隔离单位，不是前端页面或组件。
- **资源**：需要授权的业务对象，并且必须属于一个业务模块。可选类型为 `api`（API 接口）、`entity`（业务实体/集合）、`mcp_server`、`mcp_tool`、`page`（页面/菜单）、`ui_action`（按钮/命令/批量操作）、`ui_component`（Tab/区域等条件渲染组件）和 `custom`。这些是授权分类，不是 AuthHub 内置的业务对象；实际名称和标识由上游服务注册。
- **权限**：对一个资源执行的动作。页面/菜单与 UI 组件只能使用 `view`/`manage`，UI 操作只能使用 `execute`/`manage`，MCP Tool 只能使用 `view`/`execute`/`manage`，API 和业务实体可以使用 `read`、`create`、`update`、`delete` 等动作。权限的资源、模块和操作由服务端校验，不能只依赖管理端下拉框。
- **角色**：权限集合；用户通过角色获得权限。用户也可关联一个或多个组织，用于组织归属和后续数据范围策略扩展。

管理端创建模块、角色和权限时不要求填写技术 ID 或编码，系统会自动生成。Python SDK 和上游服务仍可提交显式模块 ID、角色编码或权限编码，以便进行幂等同步和程序化鉴权。

## 业务系统接入

AuthHub 不会内置或调用你的 MCP Server、MCP Tool、订单 API 或前端页面；`mcp_tool` 等只是资源分类。实际资源由你的业务后端通过 `auth-hub-client` 声明和同步，例如 `knowledge` 模块下的 `search` MCP Tool，或 `orders` 模块下的 `/orders` API。

```text
浏览器 -> 业务后端 -> auth-hub-client -> AuthHub 鉴权
                    -> 通过后才执行业务 API / MCP Tool
```

业务服务启动时用 `AUTH_HUB_MODULE_REGISTRATION_KEY` 同步模块清单；浏览器请求仍携带用户的 AuthHub Bearer Token 到业务后端。业务后端以 SDK/依赖项校验权限，前端不持有注册密钥，也不直接调用模块注册接口。业务后端还可以暴露一个 `/api/session/permissions` 代理端点，供 `@auth-hub/react` 在登录后一次性加载权限快照。完整 FastAPI 示例见 [sdk/README.md](sdk/README.md)。

## 快速启动

核心包默认依赖 SQLAlchemy。`AuthHub.local()` 接受 SQLAlchemy URL；不带 scheme 的路径会按 SQLite URL 解析：

```bash
pip install -e .

# 默认 URL: sqlite+pysqlite:///authhub.db；也可传 PostgreSQL/MySQL URL
AUTH_HUB_DATABASE=./var/authhub.db uvicorn auth_hub.main:app --reload
```

启用 FastAPI 接口：

```bash
pip install -e '.[web]'
uvicorn auth_hub.main:app --reload
```

上游 Python 服务安装独立 SDK：

```bash
pip install 'auth-hub-client @ file:///path/to/auth-hub/sdk[fastapi]'
```

默认初始化一个系统级 `admin` 用户，开发密码由 `AuthHubSettings(admin_password=...)` 指定；缺少 Redis 时使用内存缓存。生产环境可传入宿主已有 SQLAlchemy Engine，或通过环境变量直接使用其 PostgreSQL/MySQL URL。

## Docker Compose

```bash
cp .env.example .env
# Set AUTH_HUB_ADMIN_PASSWORD in .env
docker compose up --build
```

服务地址为 `http://localhost:8000`，可通过 `AUTH_HUB_PORT` 覆盖端口。Compose 会启动 AuthHub 和 Redis；AuthHub 使用 Redis 保存权限缓存，使用 SQLAlchemy 的 SQLite URL 和具名卷保存 AuthHub 自身的用户、RBAC、模块、资源实例、会话和审计数据。停止容器不会删除数据；需要清空本地环境时执行 `docker compose down -v`。

管理端登录页和侧栏会显示运行中的 `v版本号 · 构建标识`。发布镜像时可设置 `AUTH_HUB_RELEASE` 与不可变的 `AUTH_HUB_BUILD`（例如 CI 构建号或 Git 提交短哈希）；两者由 `/api/meta` 无缓存返回，用于确认浏览器实际连接到的服务版本。

管理端在 `http://localhost:8000/admin`，首次登录使用 `.env` 中的管理员用户名和密码。

管理端前端位于 `src/auth_hub/web/`：`templates/admin.html` 是页面结构，`static/admin.css` 是管理端样式，`static/admin.js` 是 API 交互逻辑。FastAPI 仅将它们作为 `/admin` 和 `/admin/assets/*` 提供，Python 后端不内嵌前端代码。构建 wheel 时会一并包含这些资源。

这是一个可零配置启动的开发/单机部署组合。生产环境将 `AUTH_HUB_DATABASE` 改为 PostgreSQL/MySQL SQLAlchemy URL，并接入 Redis 客户端和密钥服务；不会由 AuthHub 创建、部署或关闭这些外部基础设施。

## 当前 API

- `POST /api/auth/login`：用户名密码登录并签发 Token
- `POST /api/auth/refresh`、`POST /api/auth/logout`
- `GET /api/auth/me`、`POST /api/auth/check-token`
- `POST /api/auth/check`、`POST /api/auth/check/batch`、`POST /api/auth/check-resource`
- `GET /api/auth/user-permissions`
- `POST /api/modules/register`：幂等保存业务模块及权限元数据
- `POST /api/resources`、`DELETE /api/resources/{resource_id}`：管理模块下的资源定义
- `POST /api/resource-instances`、`DELETE /api/resource-instances?resource_id=...&external_id=...`：业务服务幂等登记/注销记录的外部 ID、用户归属和组织归属
- `GET`、`PUT /api/resource-instances/{instance_id}/grants`：系统管理员查看或替换一个资源实例的协作者操作权限
- `GET`、`PUT /api/resource-instances/by-external/grants`：资源 owner 或系统管理员按 `resource_id + external_id` 查看或替换该实例授权，不暴露内部实例 ID
- `GET /api/auth/users/resolve?username=...`：已登录用户按精确用户名解析一个可授权对象；不提供可枚举的用户目录
- `POST /api/permissions`：创建资源操作权限，并可同时授予角色

鉴权失败统一返回 `code`，包括 `UNAUTHENTICATED`、`TOKEN_INVALID`、`USER_DISABLED`、`PERMISSION_DENIED` 等。

## 数据库与 Redis 接入

数据库和 Redis 是“由宿主提供、由框架接入”，不是“框架完全不使用”。

```python
from auth_hub import AuthHub, AuthHubSettings, RedisCache

# SQLite、PostgreSQL、MySQL 使用同一个 SQLAlchemy Repository。
repository = SQLAlchemyAuthHubRepository("postgresql+psycopg://user:password@db/authhub")
redis_cache = RedisCache(redis_client, namespace="my-service:authhub:")
hub = AuthHub(repository, redis_cache, token_service, password_hasher, audit_log, AuthHubSettings())
```

如果宿主没有 Redis，可以先使用 `InMemoryCache()`；数据库始终通过 SQLAlchemy 接入，开发环境使用 SQLite URL，生产环境直接替换为宿主的 PostgreSQL/MySQL URL 或 Engine。缺少 SQLAlchemy 会在启动时明确报错，绝不会回退到裸 `sqlite3`。

框架不会创建或部署外部基础设施，也不会关闭宿主传入的数据库连接池或 Redis 客户端。

## 业务资源实例归属

资源定义例如 `orders:entity:order` 只描述哪类对象需要授权。业务服务创建订单后注册归属索引，不上传订单业务字段：

```json
{
  "resource_id": "orders:entity:order",
  "external_id": "order-10001",
  "owner_user_id": "user-uuid",
  "organization_id": "org-uuid"
}
```

权限范围可选 `global`、`owner`、`organization`。业务后端调用 `POST /api/auth/check-resource` 或 Python SDK 的 `check_resource_or_raise()` 时，AuthHub 先检查角色权限，再检查此实例归属。系统超级管理员对已存在的资源实例始终允许操作。业务数据库仍是订单、文档等字段的唯一真相源。

对于临时协作、某个 MCP Server 的维护人或单条记录的例外访问，系统管理员可以在管理端“资源实例 -> 协作授权”中为指定用户授予该实例所属资源的具体操作权限。业务系统也可以基于 `by-external/grants` 让该记录的 owner 管理自身记录的协作者，例如让 Skill 创建者授予同事该 Skill 的执行权。这个授权只对一个 `resource_id + external_id` 生效，不会修改用户角色，也不会扩展到同类型的其他记录；在 `check-resource` 中命中时结果为 `matched_by: "resource_grant"`。角色仍是默认的批量授权方式，实例授权只用于明确的记录级例外。

业务服务在自身事务成功后幂等调用“登记/更新归属”；删除业务记录后幂等调用“注销”。这是一致性索引，不是业务数据副本：短暂同步失败应由业务服务通过 outbox、重试队列或定期对账补偿，不能由 AuthHub 反向修改业务表。`auth-hub-client[sqlalchemy]` 已提供事务型 Outbox、提交后投递和重试能力，业务服务只需将其 `auth_hub_outbox` 表纳入自己的迁移。为防止丢失仍在使用的归属索引，资源定义或模块在存在资源实例时会拒绝删除。

## 后续阶段

1. 固化 OpenAPI/错误码/Token 响应契约。
2. 为 SQLAlchemy Repository 提供迁移脚本、事务边界与并发更新策略。
3. 固化管理端的 OpenAPI/静态资源发布和端到端测试。
4. 发布 `auth-hub-client` 到私有 PyPI，并以版本化契约测试保证兼容性。
