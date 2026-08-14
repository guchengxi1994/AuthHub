import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  Permission,
  PermissionButton,
  PermissionProvider,
  ResourcePermission,
  ResourcePermissionProvider,
  filterByPermission,
  usePermission,
} from "../src/index";

describe("AuthHub React permission rendering", () => {
  it("hides unauthorized content and renders authorized content", () => {
    const html = renderToStaticMarkup(
      <PermissionProvider permissions={["orders:ui_action:create:execute"]}>
        <Permission permission="orders:ui_action:create:execute"><span>create</span></Permission>
        <Permission permission="orders:ui_action:delete:execute"><span>delete</span></Permission>
      </PermissionProvider>,
    );

    expect(html).toContain("create");
    expect(html).not.toContain("delete");
  });

  it("supports any-match checks for alternative permissions", () => {
    const html = renderToStaticMarkup(
      <PermissionProvider permissions={["orders:ui_action:admin:manage"]}>
        <Permission
          permission={["orders:ui_action:edit:execute", "orders:ui_action:admin:manage"]}
          match="any"
        >
          <span>edit</span>
        </Permission>
      </PermissionProvider>,
    );

    expect(html).toContain("edit");
  });

  it("can disable a single unauthorized action without fetching again", () => {
    const html = renderToStaticMarkup(
      <PermissionProvider permissions={[]}>
        <PermissionButton permission="orders:ui_action:create:execute" mode="disabled">
          <button type="button">create</button>
        </PermissionButton>
      </PermissionProvider>,
    );

    expect(html).toContain('disabled=""');
    expect(html).toContain('aria-disabled="true"');
  });

  it("filters menus while preserving entries without a permission", () => {
    const items = [
      { label: "Orders", permission: "orders:page:list:view" },
      { label: "Settings" },
      { label: "Admin", permission: "admin:page:view" },
    ];
    const html = renderToStaticMarkup(
      <PermissionProvider permissions={["orders:page:list:view"]}>
        <MenuProbe items={items} />
      </PermissionProvider>,
    );

    expect(html).toContain("Orders");
    expect(html).toContain("Settings");
    expect(html).not.toContain("Admin");
  });

  it("keeps resource-level content hidden until its asynchronous decision resolves", () => {
    const html = renderToStaticMarkup(
      <ResourcePermissionProvider checkResource={async () => ({ allowed: true })}>
        <ResourcePermission
          request={{ permission: "mcp:mcp_server:server:manage", resourceId: "mcp:mcp_server:server", externalId: "server-100" }}
          loadingFallback={<span>checking</span>}
        >
          <button type="button">manage</button>
        </ResourcePermission>
      </ResourcePermissionProvider>,
    );

    expect(html).toContain("checking");
    expect(html).not.toContain("manage");
  });
});

function MenuProbe({ items }: { items: readonly { label: string; permission?: string }[] }) {
  const state = usePermission();
  return <>{filterByPermission(items, item => item.permission, state).map(item => <span key={item.label}>{item.label}</span>)}</>;
}
