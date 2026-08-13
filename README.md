# AuthHub

AuthHub 是一个独立的企业级认证与 RBAC 授权基础框架。它只负责用户、组织、角色、权限、动态模块、Token/Session 和审计，不承载具体业务模块，也不托管业务数据库或 Redis。

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
       上游提供的 SQL 数据库、Redis、密钥服务
```

`src/auth_hub/domain` 没有任何 Web、ORM 或 Redis 依赖；`src/auth_hub/ports` 是生产适配器需要实现的接口；`infrastructure.py` 仅提供开发/测试用内存实现。

## 快速启动

核心包零运行时依赖：

```bash
pip install -e .
```

启用 FastAPI 接口：

```bash
pip install -e '.[web]'
uvicorn auth_hub.main:app --reload
```

默认初始化一个系统级 `admin` 用户，开发密码由 `AuthHubSettings(admin_password=...)` 指定；生产环境必须替换为外部密码哈希器和持久化仓储。

## 当前 API

- `POST /api/auth/login`：用户名密码登录并签发 Token
- `POST /api/auth/refresh`、`POST /api/auth/logout`
- `GET /api/auth/me`、`POST /api/auth/check-token`
- `POST /api/auth/check`、`POST /api/auth/check/batch`
- `GET /api/auth/user-permissions`
- `POST /api/modules/register`：幂等保存业务模块及权限元数据

鉴权失败统一返回 `code`，包括 `UNAUTHENTICATED`、`TOKEN_INVALID`、`USER_DISABLED`、`PERMISSION_DENIED` 等。

## 生产接入

实现 `AuthHubRepository`、`Cache`、`TokenService`、`PasswordHasher` 和 `AuditLog`，然后注入 `AuthHub(...)`。数据库连接、Redis 客户端、JWT/Session 密钥和生命周期均由宿主服务管理，框架不会创建或部署这些基础设施。

## 后续阶段

1. 完成 SQLAlchemy/PostgreSQL/MySQL 仓储适配器和 Redis 缓存适配器（仍由宿主传入连接）。
2. 固化 OpenAPI/错误码/Token 响应契约。
3. 增加 admin Web（Tailwind CSS）和完整管理 API。
4. API 稳定后再制作 `auth-hub-client` Python SDK，并以版本化契约测试保证兼容性。

