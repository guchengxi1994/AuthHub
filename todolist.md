# AuthHub 框架开发 Todo List

> 本文件根据 AuthHub 设计文档整理，作为后续实现、评审和验收清单。
>
> 状态说明：
> - `[x]` 已完成并有代码或测试支撑
> - `[~]` 已有初步实现，但不完整或仅适用于开发环境
> - `[ ]` 尚未实现
> - `[!]` 需要在实现前确认设计或接口契约

## 0. 当前对照结论

当前仓库已经完成的是一个“可本地部署的框架 MVP”，不是设计文档要求的完整生产级 AuthHub。已经具备领域模型、认证/RBAC 基础用例、可注入端口、SQLite 本地持久化兜底、内存缓存兜底、Redis 客户端适配器、可撤销 opaque Token/Session、SQLite 审计、管理 API 和同服务 Admin Web；生产 SQLAlchemy/PostgreSQL/MySQL Repository、生产密码哈希、OpenAPI 契约、请求级安全测试、部署安全策略和 SDK 等仍未完成。

因此后续顺序应为：

1. 先完成并确认 AuthHub 框架设计和服务端 API 契约。
2. 再实现生产级数据库、Redis、Token 和管理端适配器。
3. 再实现 Admin Web。
4. 最后基于稳定 API 制作 `auth-hub-client` Python SDK。

## 1. 核心目标与边界

### 1.1 产品目标

- [x] 项目定位为独立的企业级认证与授权基础框架。
- [x] 以 RBAC 为第一阶段核心能力。
- [ ] 成为统一认证中心：负责“你是谁”。
- [ ] 成为统一授权中心：负责“你能做什么”。
- [ ] 为多个上游业务服务提供稳定、低耦合的鉴权 API。
- [ ] 支持 MCP Gateway、MCP Server、MCP Tool、Agent 等外部业务资源接入。

### 1.2 必须保持的边界

- [x] 不承载具体业务模块实现。
- [x] 不实现业务 API。
- [x] 不管理具体业务数据。
- [x] 不托管业务数据库生命周期，但支持接入宿主数据库连接。
- [x] 不托管业务 Redis 生命周期，但支持接入宿主 Redis 客户端。
- [ ] 不管理文件存储。
- [ ] 不实现 MCP Server。
- [ ] 不实现 Agent。
- [ ] 不侵入上游业务系统的数据模型。
- [ ] 不把业务模块、业务表和业务逻辑写死在框架内。

### 1.3 设计原则

- [x] 核心领域逻辑与 HTTP 解耦。
- [x] 核心领域逻辑与数据库解耦。
- [x] 核心领域逻辑与 Redis 解耦。
- [x] 核心领域逻辑与 Web UI 解耦。
- [~] 通过端口和依赖注入替换基础设施。
- [ ] 保持核心 API、领域模型和权限模型稳定。
- [ ] 优先简洁、可维护、可扩展，不引入没有实际价值的复杂设计。

## 2. 基础设施与依赖注入

### 2.1 数据库与持久化

- [x] 定义 Repository 抽象端口。
- [x] 提供仅用于开发/测试的内存 Repository。
- [x] 提供 SQLite 本地持久化 Repository 兜底。
- [x] 提供 Docker Compose 本地持久化启动方式（SQLite 卷）。
- [x] SQLite 保存 AuthHub 自身用户、RBAC、模块、资源、会话和审计数据。
- [ ] 明确数据库连接由宿主服务传入的配置契约。
- [ ] 实现 SQLAlchemy Repository 适配器。
- [ ] 支持 PostgreSQL。
- [ ] 支持 MySQL。
- [ ] 验证 Repository 不依赖具体业务数据库连接生命周期。
- [ ] 禁止框架自动创建数据库。
- [ ] 禁止框架自动部署数据库。
- [ ] 禁止框架自动管理数据库连接池生命周期，除非宿主明确托管。
- [ ] 设计事务边界和并发更新策略。
- [ ] 设计数据迁移文件，但迁移执行由宿主或部署系统负责。
- [ ] 设计软删除、启用/禁用和审计字段规范。

### 2.2 Redis 与缓存

- [x] 定义 Cache 抽象端口。
- [x] 提供仅用于开发/测试的内存 Cache。
- [x] 提供接收宿主 redis-py 客户端的 Redis Cache 适配器。
- [x] Redis 客户端由宿主服务注入。
- [x] Docker Compose 可启动 Redis，并由 AuthHub 实际用于权限缓存和会话 Token。
- [x] Redis 不作为最终数据源，SQLite/宿主 Repository 是用户、RBAC、模块和资源真相来源。
- [x] 设计并实现 opaque Token/Session 缓存能力。
- [ ] 设计登录状态缓存能力。
- [x] 设计权限缓存能力。
- [x] 设计用户权限缓存能力。
- [ ] 设计验证码缓存能力。
- [x] 使用 session version 实现按用户会话撤销，不依赖枚举黑名单 key。
- [ ] 设计缓存 Key 命名空间和版本号。
- [~] 实现权限缓存 TTL 与 Token/Refresh Token TTL 默认值；环境/配置映射待补齐。
- [ ] 设计主动失效接口，支持用户、角色、权限变更后的缓存失效。
- [x] 用户禁用后主动撤销该用户全部会话并立即影响鉴权。
- [~] Redis 不可用时可显式降级到 InMemoryCache；生产降级/告警策略待补齐。

### 2.3 其他基础设施端口

- [x] 定义 TokenService 端口。
- [x] 定义 PasswordHasher 端口。
- [x] 定义 AuditLog 端口。
- [x] 提供内存 Token 实现、SQLite Token fallback 和 Cache/Redis Token 实现。
- [ ] 提供生产级 JWT 实现或可替换 JWT 适配器。
- [~] 提供 Redis-compatible CacheTokenService；生产密钥、可观测性和高可用策略待补齐。
- [ ] 支持外部密钥/密钥轮换服务。
- [ ] 明确密码哈希算法要求，生产环境优先 Argon2id 或 bcrypt。
- [ ] 明确密钥、密码和 Token 不得写入日志。

## 3. 核心领域模型

### 3.1 User

- [x] 用户 ID。
- [x] 用户名。
- [x] 密码哈希。
- [x] 基本信息。
- [x] 启用/禁用状态。
- [x] 系统级超级管理员标识。
- [x] 用户创建用例。
- [x] 用户更新用例。
- [x] 用户禁用用例。
- [x] 用户删除采用安全停用，不删除审计/关系历史。
- [ ] 用户登录状态查询。
- [x] 用户角色关系。
- [~] 用户组织关系。
- [x] 用户禁用后主动撤销该用户全部会话，并阻断后续鉴权。
- [ ] 用户名、邮箱等唯一性约束在生产 Repository 中落实。

### 3.2 内置 admin

- [x] 启动时初始化系统级 `admin` 用户。
- [x] admin 不依赖上游业务系统。
- [x] admin 可绕过普通 RBAC 权限检查。
- [ ] 首次启动强制修改默认密码。
- [ ] 禁止通过普通管理 API 删除 admin。
- [x] 禁止禁用最后一个系统管理员。
- [x] 记录 admin 登录和通过 API 发起的管理操作审计。
- [ ] 生产环境禁止使用固定默认密码。

### 3.3 Organization

- [x] 组织 ID、名称、父组织、启用状态。
- [x] 创建组织。
- [x] 修改组织。
- [x] 组织树查询。
- [x] 用户与组织关系。
- [ ] 删除或软删除组织。
- [x] 防止循环父子关系。
- [ ] 防止删除仍有子组织的组织，或明确级联策略。
- [ ] 支持组织路径/层级查询。
- [ ] 明确用户多组织还是单组织约束。

### 3.4 Role

- [x] 角色 ID、编码、名称、描述、启用状态。
- [x] 创建角色。
- [~] 修改角色。
- [ ] 删除或软删除角色。
- [x] 给角色分配权限。
- [x] 给用户分配角色。
- [x] 角色权限查询。
- [x] 用户角色查询。
- [x] 内置角色保护。
- [ ] 角色编码唯一约束。
- [ ] 角色变更后的缓存失效和审计。

### 3.5 Permission

- [x] 权限 ID、编码、名称、描述、模块归属、类型和元数据。
- [x] 支持模块权限。
- [x] 支持 API/接口权限元数据。
- [x] 支持操作权限。
- [~] 预留资源权限字段。
- [ ] 明确资源级授权输入模型。
- [ ] 不固定权限编码格式。
- [ ] 支持上游自定义权限标识，例如 `mcp:server:create`。
- [x] 权限不存在时返回 `PERMISSION_NOT_FOUND`。
- [x] 权限启用/禁用。
- [ ] 权限编码唯一约束。

### 3.6 Resource 与未来扩展字段

- [x] ResourceDefinition 模型。
- [x] 资源实例持久化模型（SQLite/内存）。
- [ ] resource_type/resource_key 约束。
- [ ] 数据权限上下文模型。
- [ ] 条件表达式或策略引用字段。
- [ ] 保证当前 RBAC 模型不阻塞资源级权限扩展。

## 4. 动态模块注册

- [x] AuthHub 不预定义业务模块。
- [x] 定义模块元数据模型。
- [x] 定义模块 ID、名称、描述、metadata。
- [x] 接收 API 元数据。
- [x] 接收权限元数据。
- [x] 接收资源元数据。
- [x] 提供 `POST /api/modules/register` 初版路由。
- [x] 支持重复注册覆盖保存，并清理过期模块权限和资源。
- [ ] 明确幂等键和版本/更新时间策略。
- [ ] 明确模块删除、下线和禁用策略。
- [ ] 支持菜单元数据（可选，不与前端实现耦合）。
- [ ] 模块注册权限仅允许系统管理员或服务凭据。
- [~] SQLite 单操作持久化；完整事务边界待生产 Repository 实现。
- [ ] 模块注册结果返回新增、更新、未变化统计。
- [x] 模块同步审计。
- [ ] 为 MCP Server、MCP Tool、Agent 编写注册示例。

## 5. 认证与授权 API

### 5.1 认证接口

- [x] `POST /api/auth/login`。
- [x] `POST /api/auth/refresh`。
- [x] `POST /api/auth/logout`。
- [x] `POST /api/auth/check-token`。
- [x] `GET /api/auth/me`。
- [~] Token 机制与业务模块解耦。
- [ ] 统一请求/响应 envelope。
- [x] 统一领域错误响应结构。
- [~] 已映射 401、403、404、409、422；限流与 500 错误策略待补齐。
- [ ] 登录失败次数限制。
- [ ] 验证码能力。
- [ ] 暴力破解防护。
- [ ] 登录设备/会话管理。
- [ ] admin 登录安全策略。

### 5.2 授权接口

- [x] `POST /api/auth/check`。
- [x] `POST /api/auth/check/batch`。
- [~] 使用 Bearer Token 推导当前用户。
- [ ] 是否兼容受信任网关传入 user_id，需要明确安全边界。
- [x] 返回 `allowed`。
- [x] 返回 `authenticated`。
- [x] 返回 permission。
- [x] 返回 user_id。
- [x] 返回 reason。
- [x] 区分未认证、用户不存在、用户禁用、Token 无效、权限不足。
- [x] 区分权限不存在。
- [x] 区分系统管理员。
- [x] 支持资源和 context 入参占位。
- [ ] 明确 `resource` 和 `context` 的正式语义。
- [ ] 提供 `/check-token`、`/user-info`、`/user-permissions` 的稳定契约。
- [ ] 明确批量接口部分成功和整体失败策略。

### 5.3 管理接口

- [x] `GET/POST/PATCH /api/users` 初版。
- [x] `GET/POST /api/organizations` 初版。
- [x] `GET/POST /api/roles` 初版。
- [x] `GET /api/permissions` 初版。
- [x] 用户角色分配初版。
- [x] 角色权限分配初版。
- [x] 用户安全停用（删除）/恢复（enabled=true）。
- [x] 组织修改/删除。
- [x] 角色修改/删除。
- [x] 模块查询/同步/删除。
- [~] 权限查询、创建、启停和模块批量同步；权限删除待设计。
- [ ] 分页、过滤、排序和审计字段。
- [ ] 管理接口全部纳入权限控制，而不仅是 admin 特判。

## 6. Token / Session 设计

- [x] Authentication 与 Authorization 分离。
- [x] 登录返回 access token。
- [x] 登录返回 refresh token。
- [x] Token 校验映射到用户。
- [x] Token 刷新。
- [x] Token 注销。
- [~] 开发环境内存 Token。
- [ ] 决定 JWT、Opaque Token 或两者并存。
- [ ] 定义 access token TTL。
- [ ] 定义 refresh token TTL。
- [ ] 定义 refresh token 轮换策略。
- [ ] 定义 Token 载荷、issuer、audience、subject、scope。
- [ ] 定义密钥管理和轮换。
- [ ] 定义 Token 黑名单/撤销策略。
- [ ] 定义多设备登录和单点注销策略。
- [ ] 定义跨服务 Token 校验策略。
- [ ] 定义网关层校验与业务服务二次鉴权策略。

## 7. 权限缓存设计

- [x] User -> Roles -> Permissions 查询逻辑。
- [x] 用户权限结果缓存。
- [x] TTL 配置项。
- [x] 用户角色变更主动失效。
- [x] 角色权限变更主动失效。
- [x] 用户禁用后主动撤销会话并立即拒绝鉴权。
- [x] Redis-compatible Cache/Session 适配器。
- [ ] 完整缓存 Key 设计，例如：
  - [ ] `authhub:user:{user_id}`
  - [x] `authhub:permissions:{user_id}`（namespace 由 RedisCache 注入）
  - [ ] `authhub:role-permissions:{role_id}:v{version}`
  - [x] `authhub:session:access:{sha256(token)}`
  - [x] `authhub:session:refresh:{sha256(token)}`
  - [x] `authhub:session:user:{user_id}:version`
- [ ] 缓存版本号或权限版本号。
- [x] 角色影响用户集合的失效策略。
- [ ] 模块/权限同步后的失效策略。
- [ ] Redis 故障时回源数据库策略。
- [ ] 防止缓存击穿和缓存污染。

## 8. Admin Web

- [x] 选择前后端同服务部署方式。
- [x] 使用 FastAPI 内置 HTML 响应和 CDN Tailwind/Lucide 的本地启动方案。
- [x] 使用 Tailwind CSS。
- [ ] 不引入大型 UI 框架，除非评审后确有必要。
- [x] admin 登录页。
- [x] 用户管理页。
- [x] 组织树管理页。
- [x] 角色管理页。
- [x] 模块管理页。
- [~] 权限管理通过角色配置弹窗完成；独立页面待补齐。
- [x] 角色权限配置页。
- [x] 用户角色配置页。
- [ ] 基础系统配置页。
- [x] 登录态、Token 过期和退出处理。
- [x] 表格、树、表单、权限勾选交互。
- [ ] loading、空状态、错误状态和权限不足状态。
- [ ] 不显示业务模块实现，只展示注册元数据。
- [x] 管理操作审计查看能力。

## 9. 架构模块拆分

- [x] `domain`：领域模型和错误。
- [x] `ports`：Repository、Cache、Token、Hasher、AuditLog 端口。
- [x] application/use-case 层初版。
- [~] authentication 模块，目前散落在 application/api。
- [~] authorization 模块，目前散落在 application/api。
- [~] user 模块，目前以 application 方法存在。
- [~] organization 模块，目前以 application 方法存在。
- [~] role 模块，目前以 application 方法存在。
- [~] permission 模块，目前以 application 方法存在。
- [~] module 模块，目前以 application 方法存在。
- [x] resource 模块：模型、内存/SQLite 持久化、模块同步和查询 API。
- [x] token 模块：端口、内存/SQLite/Cache 实现、refresh rotation 和用户会话撤销。
- [x] audit 模块：AuditLog 端口、内存/SQLite 实现及查询 API。
- [ ] 按模块拆分用例、端口和 API，避免 application.py 继续膨胀。
- [ ] controller/router 与用例层彻底分离。
- [ ] 统一 DTO 与领域实体转换。
- [ ] 统一配置、日志、异常和依赖注入入口。

## 10. 未来扩展路线

- [x] 当前以 RBAC 为核心。
- [~] 为数据权限预留 `resource/context`。
- [ ] RBAC + 数据权限。
- [ ] 资源级权限。
- [ ] ABAC 属性模型。
- [ ] 条件权限。
- [ ] 策略版本化。
- [ ] 策略解释/审计：说明为什么允许或拒绝。
- [ ] 不让当前权限编码和关系模型阻塞后续策略扩展。

## 11. 安全、错误、日志和可观测性

- [x] 统一领域错误码初版。
- [x] HTTP 错误映射初版。
- [ ] 全局 request id/correlation id。
- [ ] 结构化日志。
- [~] 登录成功审计；失败登录审计待补齐。
- [~] Token 签发随登录审计；刷新/注销审计待补齐。
- [x] 授权允许/拒绝审计。
- [x] 用户、组织、角色、权限关系、模块管理审计。
- [ ] 密码、Token、Redis key 等敏感信息脱敏。
- [ ] 登录限流和 IP/账户防护。
- [ ] 权限检查接口限流。
- [ ] CORS、Trusted Host、反向代理配置。
- [ ] 健康检查和就绪检查。
- [ ] 指标：登录失败率、鉴权耗时、缓存命中率、Token 失败率。
- [ ] OpenTelemetry 或等价 tracing 接口（可选）。

## 12. 测试策略

- [x] 领域/应用层基础单元测试。
- [x] admin 登录测试。
- [x] RBAC 允许/拒绝测试。
- [x] 用户禁用测试。
- [x] 权限缓存失效测试。
- [x] SQLite 会话和审计跨实例持久化测试。
- [x] Refresh Token 单次使用/轮换测试。
- [x] 用户禁用全会话撤销测试。
- [x] 组织循环约束测试。
- [x] 模块权限/资源同步清理测试。
- [ ] Repository 契约测试，所有数据库实现共用。
- [ ] Cache 契约测试，内存/Redis 实现共用。
- [ ] TokenService 契约测试。
- [ ] API 请求级测试。
- [ ] API 错误码和状态码测试。
- [ ] 并发登录和并发权限变更测试。
- [x] Token 撤销、刷新轮换测试；TTL 边界待补齐。
- [x] 模块重复注册和更新测试。
- [x] 组织循环约束测试；删除约束待补齐。
- [ ] 安全测试：越权、伪造 Token、重放、暴力破解。
- [ ] 性能测试：单次鉴权、批量鉴权、缓存命中和回源。
- [ ] SDK 契约测试（框架 API 稳定后）。

## 13. 文档与交付物

- [x] 初版 README。
- [x] 初版项目打包配置。
- [x] 初版项目目录。
- [x] 本开发 Todo 清单。
- [ ] 整体架构设计文档。
- [ ] 模块职责与依赖关系文档。
- [ ] 核心领域模型文档。
- [ ] 数据库表设计文档。
- [ ] API/OpenAPI 文档。
- [ ] Token/Session 设计文档。
- [ ] RBAC 权限模型文档。
- [ ] 动态模块注册协议文档。
- [ ] Redis 缓存设计文档。
- [ ] Admin Web 页面结构文档。
- [ ] 生产部署与安全配置文档。
- [ ] Python SDK 使用文档。
- [ ] 版本兼容和变更日志。

## 14. 推荐实施阶段

### Phase 0：设计冻结

- [ ] 评审并冻结领域模型。
- [ ] 评审并冻结错误码。
- [ ] 评审并冻结认证/授权 API。
- [ ] 评审 JWT/Opaque Token 选择。
- [ ] 评审多租户和组织关系是否需要第一阶段支持。
- [ ] 评审模块注册幂等规则。
- [ ] 评审 SDK 的目标调用方式，但暂不实现 SDK。

### Phase 1：框架核心

- [x] 领域模型和端口。
- [x] 内存 Repository/Cache/Token/Hasher/Audit 实现。
- [x] SQLite 数据库和内存缓存 fallback。
- [x] Redis 客户端接入适配器。
- [x] admin bootstrap。
- [x] login、me、check、batch check、logout、refresh。
- [x] 基础用户、组织、角色、权限管理用例。
- [x] 模块注册和资源同步。
- [x] 权限缓存失效和用户会话撤销。
- [~] SQLite 审计和查询；生产 AuditLog、失败登录/Token 生命周期审计待补齐。
- [ ] 领域模块拆分。

### Phase 2：生产基础设施

- [ ] SQLAlchemy Repository。
- [ ] PostgreSQL/MySQL 验证。
- [ ] Redis Cache/Session/Blacklist。
- [ ] 生产密码哈希。
- [ ] 生产 Token 服务。
- [ ] 数据迁移和索引设计。
- [ ] 事务和并发控制。

### Phase 3：正式 API

- [ ] OpenAPI 契约冻结。
- [ ] DTO、分页、过滤、排序。
- [~] 管理 API：基础 CRUD 和关系管理已完成，分页/过滤/独立权限模型待补齐。
- [~] 模块/资源 API：同步、查询、删除已完成，版本与下线策略待补齐。
- [ ] 统一错误、日志、request id。
- [ ] API 级安全测试。

### Phase 4：Admin Web

- [x] Tailwind CSS 基础布局。
- [x] admin 登录。
- [~] 用户、组织、角色、模块、审计页面；独立权限/系统配置页待补齐。
- [x] 权限分配交互。
- [x] 前后端同服务部署。
- [ ] 生产构建和静态资源发布。

### Phase 5：Python SDK

- [ ] 从正式 OpenAPI/契约生成或实现 SDK。
- [ ] 同步客户端。
- [ ] 异步客户端。
- [ ] Token 注入与请求上下文。
- [ ] 单个/批量鉴权封装。
- [ ] 模块注册封装。
- [ ] 标准异常和重试策略。
- [ ] SDK 版本与服务端兼容矩阵。
- [ ] 发布到 PyPI/私有 PyPI。

### Phase 6：扩展能力

- [ ] 数据权限。
- [ ] 资源级权限。
- [ ] ABAC。
- [ ] 条件策略。
- [ ] Gateway 集成示例。
- [ ] MCP Server/Tool/Agent 集成示例。

## 15. 当前实现与设计文档差距

| 设计领域 | 当前状态 | 主要差距 |
| --- | --- | --- |
| 架构边界 | 初步完成 | 需要正式架构文档和稳定模块边界 |
| 领域模型 | 初步完成 | 缺少完整资源、状态、删除、版本字段 |
| 数据库 | 未完成 | 只有 Repository 协议和内存实现 |
| Redis | 初步完成 | Redis Cache/Session 已接入，缺故障降级与生产运行策略 |
| 认证 | MVP 完成 | SQLite/Redis opaque Token，缺生产密钥、限流和安全策略 |
| 授权 | MVP 完成 | 已区分权限不存在并持久化资源，资源条件与策略解释未完成 |
| 动态模块 | MVP 完成 | 幂等覆盖、旧权限/资源清理完成，缺版本、事务、菜单和同步结果 |
| 管理 API | MVP 完成 | CRUD/关系管理/审计完成，缺分页、过滤和细粒度管理权限 |
| Admin Web | 未开始 | 设计文档要求的前端全部未实现 |
| 审计 | 原型完成 | 只有内存日志，缺查询、持久化和脱敏 |
| 测试 | 初版完成 | 缺 API、基础设施契约、安全和性能测试 |
| SDK | 按计划未开始 | 必须等待 API 契约稳定后实现 |

## 16. 当前验收门槛

在进入 SDK 阶段前，至少必须满足：

- [ ] API 路径、请求体、响应体和错误码冻结。
- [~] opaque Token/Session 已实现；生产策略和配置尚未冻结。
- [ ] 数据库和 Redis 适配器通过契约测试。
- [~] 用户、组织、角色、权限、模块管理 API 基础闭环可用；分页/过滤/细粒度权限待补齐。
- [x] 鉴权接口覆盖 Bearer Token、批量检查和权限不存在场景。
- [x] 用户禁用、角色权限变化能够立即影响授权结果。
- [x] Admin Web 能完成基础配置闭环。
- [ ] OpenAPI 文档可作为 SDK 的唯一接口来源。
- [ ] 服务端和 SDK 有兼容性测试。
