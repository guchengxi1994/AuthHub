# @auth-hub/react

`@auth-hub/react` is a lightweight React-only rendering SDK. It decides whether to show a route, menu entry, button, Tab, or arbitrary component from an already-authenticated user's permission snapshot.

It is a user-experience layer, not the authorization boundary: every business API and MCP Tool must still use the Python `auth-hub-client` to enforce the same permission server-side.

## Install

```bash
npm install @auth-hub/react react react-dom
```

For local development in this repository:

```bash
cd web-sdk
npm install
npm run build
```

## One Request Per Session

Do not call AuthHub once per button. Your business backend exposes an authenticated endpoint such as `/api/session/permissions`, which proxies AuthHub's `GET /api/auth/user-permissions` through the Python SDK. The React provider loads that snapshot once after login.

```tsx
import { PermissionProvider } from "@auth-hub/react";

async function loadPermissions(accessToken: string) {
  const response = await fetch("/api/session/permissions", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error("Unable to load permissions");
  return response.json(); // { permissions: ["orders:page:order-list:view", ...] }
}

export function AppRoot() {
  const accessToken = getAccessTokenFromYourSession();
  return (
    <PermissionProvider loadPermissions={() => loadPermissions(accessToken)} loadingFallback={<AppSkeleton />}>
      <App />
    </PermissionProvider>
  );
}
```

Use `refreshKey={sessionId}` when the authenticated session changes, or use `refresh()` from `usePermission()` after role changes. A cookie-backed business session is also valid, provided the business endpoint translates it to the AuthHub token before calling AuthHub.

## Routes, Menus, And Actions

All frontend checks use the same permission codes that the Python backend checks.

```tsx
import { Permission, PermissionRoute, filterByPermission, usePermission } from "@auth-hub/react";

const permissions = {
  ordersPage: "orders:page:order-list:view",
  createOrder: "orders:ui_action:order-create:execute",
  exportOrders: "orders:ui_action:order-export:execute",
};

function Routes() {
  return (
    <Route
      path="/orders"
      element={
        <PermissionRoute permission={permissions.ordersPage} forbidden={<Navigate to="/403" replace />}>
          <OrdersPage />
        </PermissionRoute>
      }
    />
  );
}

function OrdersToolbar() {
  return (
    <>
      <Permission permission={permissions.createOrder}>
        <button type="button">创建订单</button>
      </Permission>
      <Permission permission={permissions.exportOrders}>
        <button type="button">导出</button>
      </Permission>
    </>
  );
}

function Navigation() {
  const permission = usePermission();
  const menus = filterByPermission(allMenus, menu => menu.permission, permission);
  return <Menu items={menus} />;
}
```

`Permission` defaults to hiding unauthorized children. Use `match="any"` when either one of several permissions is sufficient:

```tsx
<Permission permission={["orders:ui_action:order-edit:execute", "orders:ui_action:order-admin:manage"]} match="any">
  <button type="button">编辑</button>
</Permission>
```

## Resource Instances

The permission snapshot is correct for routes, menus, and ordinary actions. A concrete business record, MCP Server, or MCP Tool can additionally have an owner, an organization scope, or an administrator-managed collaboration grant. Render these elements after the business backend checks that exact record.

The browser still does not call AuthHub directly. Expose a protected business endpoint that forwards to `check_resource_or_raise()` or returns its AuthHub decision, then provide that function to the lightweight resource provider:

```tsx
import {
  ResourcePermission,
  ResourcePermissionProvider,
  type ResourcePermissionRequest,
} from "@auth-hub/react";

async function checkResource(request: ResourcePermissionRequest) {
  const response = await fetch("/api/session/check-resource", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error("Unable to check resource permission");
  return response.json(); // { allowed, authenticated, reason }
}

function ServerActions({ serverId }: { serverId: string }) {
  return (
    <ResourcePermission
      request={{
        permission: "mcp:mcp_server:server:manage",
        resourceId: "mcp:mcp_server:server",
        externalId: serverId,
      }}
      loadingFallback={<span />}
    >
      <button type="button">管理 Server</button>
    </ResourcePermission>
  );
}

function App() {
  return <ResourcePermissionProvider checkResource={checkResource} cacheKey={sessionId}><ServerActions serverId="server-100" /></ResourcePermissionProvider>;
}
```

`ResourcePermissionProvider` deduplicates equal in-flight and completed checks for the active session. It is presentation only: the actual MCP/API operation must still call the Python SDK's `require_resource_permission` or `check_resource_or_raise()`.

## Resource Registration

The React package never has a registration key and never registers resources directly. The business service registers frontend resources with its Python manifest, usually at startup:

```python
ModuleManifest(
    module_id="orders",
    name="订单中心",
    resources=[
        ResourceSpec.page("order-list", "订单列表"),
        ResourceSpec.ui_action("order-create", "创建订单"),
        ResourceSpec.ui_action("order-export", "导出订单"),
        ResourceSpec.api("/orders", "订单接口"),
    ],
    permissions=[
        PermissionSpec("view", "查看订单列表", resource="order-list"),
        PermissionSpec("execute", "创建订单", resource="order-create"),
        PermissionSpec("execute", "导出订单", resource="order-export"),
        PermissionSpec("read", "读取订单", resource="/orders"),
    ],
)
```

`page` represents route/page visibility. `ui_action` represents a button, context-menu command, batch operation, or other executable UI command. `ui_component` is for a Tab or region that is only visible with a permission. AuthHub does not need to know whether `order-create` is implemented as a button, menu item, or modal trigger.

## Security Boundary

Hiding a button is never security. A user can alter browser JavaScript. The business backend must protect `POST /orders`, exports, and MCP Tool execution using the Python SDK with the corresponding permission code. The browser SDK is intentionally only the presentation layer.
