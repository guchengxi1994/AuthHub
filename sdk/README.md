# auth-hub-client

`auth-hub-client` is installed by an upstream **Python backend**. It is not a browser SDK and it does not own the upstream service's database, API routes, or MCP execution.

```bash
pip install 'auth-hub-client @ file:///path/to/auth-hub/sdk[fastapi]'
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
from auth_hub_client import AuthHubClient, ModuleManifest, PermissionSpec, ResourceSpec, require_permission

manifest = ModuleManifest(
    module_id="knowledge",
    name="知识库服务",
    resources=[
        ResourceSpec.mcp_tool("search", "知识检索工具"),
        ResourceSpec.api("/documents", "文档接口"),
        ResourceSpec.page("document-list", "文档列表页面"),
        ResourceSpec.ui_action("document-export", "导出文档"),
        ResourceSpec.ui_component("document-sensitive-tab", "敏感信息 Tab"),
    ],
    permissions=[
        PermissionSpec("execute", "执行知识检索", resource="search"),
        PermissionSpec("read", "读取文档", resource="/documents"),
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

`require_permission` handles function-level RBAC, such as whether a user can execute the `search` tool. It intentionally does not decide which documents or orders are visible. The business API must apply its own tenant, organization, ownership, and row-level rules after AuthHub approves the operation.
