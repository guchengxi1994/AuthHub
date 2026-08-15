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

AuthHub 按三类权限组织授权，而不是把所有资源实例混为同一层：

```text
AuthHub 管理权限：管理 AuthHub 本身
业务系统操作权限：调用接口、页面、按钮或 MCP 能力
业务系统数据权限：访问某类业务数据及其具体记录
```

- **业务模块**：上游业务的边界，例如“订单中心”或“MCP 管理”。一个模块可以同时声明操作资源和数据资源。
- **角色**：权限集合；用户通过一个或多个角色取得权限，多个角色的有效权限取并集。用户也可关联一个或多个组织，用于数据范围判断。
- **权限资源**：权限对应的受控对象。资源类型和所属模块确定权限类别，服务端不会信任仅由管理台传入的类别。

### 业务系统操作权限

`api`、`mcp_server`、`mcp_tool`、`page`、`ui_action` 和 `ui_component` 都属于业务系统操作权限。例如调用一个 API、显示页面、执行按钮命令或调用 MCP Tool。

这类权限只能使用 `global` 范围：角色决定用户是否可以执行该能力。前端的页面和按钮控制只能改善体验，业务后端仍必须使用 SDK 进行操作权限校验。

### 业务系统数据权限

`entity` 和 `custom` 属于业务系统数据权限，例如订单、文档、项目、资产或其他需要逐条控制的业务对象。它们可以使用 `global`、`owner`、`organization` 范围；只有这类资源能由业务系统登记数据记录，并支持把某一条记录分享给指定用户。

数据权限不替代操作权限。更新订单等请求通常需要同时满足：调用更新接口的操作权限，以及该订单记录的 `update` 数据权限。角色表示“原则上能做什么”，归属、组织范围和逐记录分享决定“能否操作这一条数据”。

### AuthHub 内置管理权限

AuthHub 自身的管理 API 也受 RBAC 保护。启动时会幂等注册内置 `authhub` 模块及其资源，包括管理台、用户、组织、角色、权限、业务模块、资源定义、资源实例、审计日志和“授权用户精确查询”。`authhub:admin` 内置角色自动拥有全部内置权限；系统超级管理员仍保留绕过能力。

例如，查询用户列表需要 `authhub:entity:users:read`，查询组织需要 `authhub:entity:organizations:read`，查询角色的权限需要 `authhub:entity:roles:read`。可将这些权限分配给受限的运维角色，而不必授予系统超级管理员身份。管理角色只能把自己已经拥有的权限授予其他角色或用户，不能操作系统管理员或内置管理员角色。

资源 owner 发起分享时，按用户名解析收件人需要 `authhub:custom:share-recipient:read`。该权限只允许精确解析指定的已启用用户名，不提供可枚举的用户目录；应与业务资源的 owner/实例授权能力一并授予需要发起分享的角色。

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

运行时配置由 `pydantic-settings` 读取：进程环境变量优先，只有缺失的值才会从启动工作目录的 `.env` 文件读取。不会扫描父目录或根据源文件路径猜测 `.env`，以避免部署环境被意外覆盖。

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
- `POST /api/resource-instances`、`DELETE /api/resource-instances?resource_id=...&external_id=...`：业务服务幂等登记/注销业务数据记录的外部 ID、用户归属和组织归属
- `GET`、`PUT /api/resource-instances/{instance_id}/grants`：系统管理员查看或替换一个业务数据记录的用户分享
- `GET`、`PUT /api/resource-instances/by-external/grants`：记录 owner 或系统管理员按 `resource_id + external_id` 查看或替换该记录分享，不暴露内部实例 ID
- `GET /api/auth/users/resolve?username=...`：持有 `authhub:custom:share-recipient:read` 的用户按精确用户名解析一个可授权对象；不提供可枚举的用户目录
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

## 业务数据记录归属

资源定义例如 `orders:entity:order` 只描述哪类对象需要授权。业务服务创建订单后注册归属索引，不上传订单业务字段：

```json
{
  "resource_id": "orders:entity:order",
  "external_id": "order-10001",
  "owner_user_id": "user-uuid",
  "organization_id": "org-uuid"
}
```

只有业务数据权限可选 `global`、`owner`、`organization`。业务后端调用 `POST /api/auth/check-resource` 或 Python SDK 的 `check_resource_or_raise()` 时，AuthHub 先检查角色权限，再检查此数据记录的归属。系统超级管理员对已存在的数据记录始终允许操作。业务数据库仍是订单、文档等字段的唯一真相源。

对于临时协作或单条数据记录的例外访问，系统管理员可以在管理端“数据记录与分享”中为指定用户授予该记录所属数据资源的具体操作权限。业务系统也可以基于 `by-external/grants` 让该记录的 owner 管理自身记录的分享用户。这个授权只对一个 `resource_id + external_id` 生效，不会修改用户角色，也不会扩展到同类型的其他记录；在 `check-resource` 中命中时结果为 `matched_by: "resource_grant"`。角色仍是默认的批量授权方式，记录分享只用于明确的数据级例外。

业务服务在自身事务成功后幂等调用“登记/更新归属”；删除业务记录后幂等调用“注销”。这是一致性索引，不是业务数据副本：短暂同步失败应由业务服务通过 outbox、重试队列或定期对账补偿，不能由 AuthHub 反向修改业务表。`auth-hub-client[sqlalchemy]` 已提供事务型 Outbox、提交后投递和重试能力，业务服务只需将其 `auth_hub_outbox` 表纳入自己的迁移。为防止丢失仍在使用的归属索引，资源定义或模块在存在资源实例时会拒绝删除。

## 后续阶段

1. 固化 OpenAPI/错误码/Token 响应契约。
2. 为 SQLAlchemy Repository 提供迁移脚本、事务边界与并发更新策略。
3. 固化管理端的 OpenAPI/静态资源发布和端到端测试。
4. 发布 `auth-hub-client` 到私有 PyPI，并以版本化契约测试保证兼容性。
