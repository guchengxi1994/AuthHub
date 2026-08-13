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
    ],
    permissions=[
        PermissionSpec("execute", "执行知识检索", resource="search"),
        PermissionSpec("read", "读取文档", resource="/documents"),
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
- `custom`: a domain-specific protected object.

Choose the type that matches the thing being protected. The actual names and keys always come from the business service's manifest.

## Data Scope

`require_permission` handles function-level RBAC, such as whether a user can execute the `search` tool. It intentionally does not decide which documents or orders are visible. The business API must apply its own tenant, organization, ownership, and row-level rules after AuthHub approves the operation.
