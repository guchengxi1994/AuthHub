# auth-hub-client

`auth-hub-client` is installed by an upstream **Python backend**. It is not a browser SDK and it does not own the upstream service's database, API routes, or MCP execution.

```bash
pip install 'auth-hub-client @ file:///path/to/auth-hub/sdk[fastapi,sqlalchemy]'
```

## Runtime Chain

```text
Browser -> business API -> auth-hub-client -> AuthHub /api/auth/check
                    |                         |
                    | allow / deny            -> RBAC decision
                    v
              business API / MCP tool
```

1. The business backend starts and syncs its declared module manifest using a registration key.
2. An administrator uses AuthHub to attach the generated permissions to roles and users.
3. The browser sends the user's AuthHub Bearer token to the business API.
4. A route dependency calls AuthHub. The business API runs only after an allow decision.

The frontend never calls the module registration endpoint and never receives the registration key.

## FastAPI Example

```python
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from auth_hub_client import AuthHubClient, ModuleManifest, PermissionSpec, ResourceSpec, require_permission, require_resource_permission

manifest = ModuleManifest(
    module_id="knowledge",
    name="知识库服务",
    resources=[
        ResourceSpec.mcp_tool("search", "知识检索工具"),
        ResourceSpec.api("/documents", "文档接口"),
        ResourceSpec.entity("order", "订单"),
        ResourceSpec.page("document-list", "文档列表页面"),
        ResourceSpec.ui_action("document-export", "导出文档"),
        ResourceSpec.ui_component("document-sensitive-tab", "敏感信息 Tab"),
    ],
    permissions=[
        PermissionSpec("execute", "执行知识检索", resource="search"),
        PermissionSpec("read", "读取文档", resource="/documents", scope="global"),
        PermissionSpec("update", "更新自己的订单", resource="order", scope="owner"),
        PermissionSpec("view", "查看文档页面", resource="document-list"),
        PermissionSpec("execute", "导出文档", resource="document-export"),
        PermissionSpec("view", "查看敏感信息 Tab", resource="document-sensitive-tab"),
    ],
)

client = AuthHubClient(
    "http://auth-hub:8000",
    registration_key="same-value-as-AUTH_HUB_MODULE_REGISTRATION_KEY",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    client.register_module(manifest)
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/mcp/search")
async def search(_: dict = Depends(require_permission(
    client,
    manifest.permission_code("search", "execute"),
))):
    return {"result": "call the real MCP tool here"}
```

For record-level authorization, register the business record after creation and check the external business ID before read/update/delete:

```python
instance = client.register_resource_instance(
    resource_id=manifest.resource_id("order"),
    external_id=str(order.id),
    owner_user_id=current_user_id,
    organization_id=current_org_id,
)

authz = client.check_resource_or_raise(
    access_token,
    manifest.permission_code("order", "update"),
    resource_id=manifest.resource_id("order"),
    external_id=str(order.id),
)
```

`manifest.resource_id("order")` derives `knowledge:entity:order` from the declared module and resource; application code should not hardcode it. Set `PermissionSpec(..., scope="owner")` or `scope="organization"` for those checks. `global` skips instance ownership checks.

The business database remains the source of truth. Create/update the business record first and then call the idempotent registration method; after deleting the business record, call `client.unregister_resource_instance(manifest.resource_id("order"), str(order.id))`. AuthHub never deletes business records and deliberately rejects deleting a resource definition or module while instance indexes remain.

## SQLAlchemy Transactional Outbox

For a production business service, do not call AuthHub from an ORM signal or a
normal decorator immediately after `INSERT`/`UPDATE`. The surrounding business
transaction can still roll back. Use the SDK's SQLAlchemy Outbox instead: it
writes the ownership event into the **same business transaction** and sends it
only after commit. This has the same intent as Spring's
`@TransactionalEventListener(AFTER_COMMIT)`, with a durable retry record.

Add `outbox.table` to your business application's normal Alembic migration
(AuthHub does not create or migrate the business schema):

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import sessionmaker
from auth_hub_client import (
    AuthHubOutbox,
    AuthHubOutboxDispatcher,
    dispatch_pending,
    install_after_commit_dispatcher,
    track_resource_instance,
    untrack_resource_instance,
)

metadata = MetaData()                 # usually your application's Base.metadata
outbox = AuthHubOutbox(metadata)      # creates the auth_hub_outbox table in metadata
SessionLocal = sessionmaker(bind=engine)

dispatcher = AuthHubOutboxDispatcher(outbox, client)
install_after_commit_dispatcher(SessionLocal, dispatcher)
```

Decorate the **service-layer methods** that own the business transaction, not
raw repository functions. The decorator only inserts an outbox event; it does
not commit and it does not make a network request itself.

```python
@track_resource_instance(
    outbox,
    resource_id=manifest.resource_id("order"),
    external_id=lambda order: order.id,
    owner_user_id=lambda order: order.creator_id,
    organization_id=lambda order: order.organization_id,
)
def create_order(*, session, command) -> Order:
    order = Order(creator_id=command.user_id, organization_id=command.org_id)
    session.add(order)
    return order

@track_resource_instance(
    outbox,
    resource_id=manifest.resource_id("order"),
    external_id=lambda order: order.id,
    owner_user_id=lambda order: order.owner_id,
    organization_id=lambda order: order.organization_id,
)
def transfer_order(*, session, order_id, owner_id) -> Order:
    order = session.get(Order, order_id)
    order.owner_id = owner_id
    return order

@untrack_resource_instance(
    outbox,
    resource_id=manifest.resource_id("order"),
    external_id=lambda order: order.id,
)
def delete_order(*, session, order_id) -> Order:
    order = session.get(Order, order_id)
    session.delete(order)
    return order

with SessionLocal.begin() as session:
    create_order(session=session, command=command)
```

`install_after_commit_dispatcher()` makes a best-effort, low-latency delivery
after a successful commit. Keep a periodic worker as the durable recovery path
for process crashes and temporary AuthHub outages:

```python
def run_authhub_outbox_worker() -> None:
    while True:
        result = dispatch_pending(SessionLocal, dispatcher, limit=100)
        if result.delivered == 0 and result.deferred == 0:
            break
```

The dispatcher uses exponential backoff and retains exhausted events as dead
letters. After correcting a configuration error, inspect the `auth_hub_outbox`
table and call `outbox.requeue(session, event_id)` to retry one. AuthHub's
registration and deletion endpoints are idempotent, so at-least-once delivery
is safe. Events for one `(resource_id, external_id)` are delivered in enqueue
order, preventing a retried old owner update from overtaking a newer event.

For a normal FastAPI route, the route dependency can get the external ID from the path parameter directly:

```python
@app.patch("/orders/{order_id}")
async def update_order(
    order_id: str,
    _: dict = Depends(require_resource_permission(
        client,
        manifest.permission_code("order", "update"),
        manifest.resource_id("order"),
        "order_id",
    )),
):
    return {"id": order_id}
```

`ResourceSpec.mcp_tool("search", ...)` means the upstream service's own tool named `search` is a protected object. It does **not** mean AuthHub contains a built-in search tool.

## Resource Types

The type is a stable authorization classification, not a hardcoded business resource:

- `api`: an endpoint, such as `/documents`.
- `entity`: a business collection, such as `order`.
- `mcp_server`: an upstream MCP server identifier.
- `mcp_tool`: an upstream tool identifier.
- `page`: a menu/page visibility identifier.
- `ui_action`: a button, context-menu command, or batch operation.
- `ui_component`: a Tab, region, or other conditionally rendered UI component.
- `custom`: a domain-specific protected object.

Choose the type that matches the thing being protected. The actual names and keys always come from the business service's manifest.

## Permission Snapshot Proxy For React

The browser SDK needs the current user's permission codes, but the browser should not call AuthHub directly. Expose a business-backend endpoint that forwards the authenticated Bearer token:

```python
from fastapi import Depends, FastAPI
from auth_hub_client import AuthHubFastAPI

auth = AuthHubFastAPI(client)
app = FastAPI()

@app.get("/api/session/permissions")
async def session_permissions(snapshot: dict = Depends(auth.permission_snapshot())):
    return snapshot  # {"permissions": ["knowledge:mcp_tool:search:execute", ...]}
```

The React app calls this endpoint once after login. If the business app stores its own session cookie, the endpoint may translate that session into the AuthHub access token before calling `permission_snapshot`; the SDK itself does not manage browser cookies or tokens.

## Data Scope

`require_permission` handles function-level RBAC, such as whether a user can execute the `search` tool. `require_resource_permission` adds AuthHub's registered owner/organization scope check for one record. The business API still owns business-record existence, tenant rules, transactions, and any richer row-level policy.
