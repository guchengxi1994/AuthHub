// src/index.tsx
import {
  createContext,
  cloneElement,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from "react";
import { jsx } from "react/jsx-runtime";
var PermissionContext = createContext(null);
function normalizeSnapshot(snapshot) {
  if (Array.isArray(snapshot)) {
    return snapshot;
  }
  return snapshot.permissions;
}
function PermissionProvider({
  children,
  permissions: suppliedPermissions,
  loadPermissions,
  refreshKey,
  loadingFallback = null,
  errorFallback
}) {
  const [loadedPermissions, setLoadedPermissions] = useState(suppliedPermissions ?? []);
  const [loading, setLoading] = useState(Boolean(loadPermissions && !suppliedPermissions));
  const [error, setError] = useState(null);
  const refresh = useCallback(async () => {
    if (!loadPermissions) return;
    setLoading(true);
    setError(null);
    try {
      setLoadedPermissions(normalizeSnapshot(await loadPermissions()));
    } catch (reason) {
      setError(reason instanceof Error ? reason : new Error("Unable to load AuthHub permissions"));
    } finally {
      setLoading(false);
    }
  }, [loadPermissions]);
  useEffect(() => {
    if (suppliedPermissions) {
      setLoadedPermissions(suppliedPermissions);
      setLoading(false);
      setError(null);
      return;
    }
    void refresh();
  }, [suppliedPermissions, refresh, refreshKey]);
  const permissionSet = useMemo(() => new Set(suppliedPermissions ?? loadedPermissions), [suppliedPermissions, loadedPermissions]);
  const value = useMemo(() => ({
    ready: !loading && !error,
    loading,
    error,
    permissions: permissionSet,
    hasPermission: (permission) => permissionSet.has(permission),
    hasAnyPermission: (permissions) => permissions.some((permission) => permissionSet.has(permission)),
    hasAllPermissions: (permissions) => permissions.every((permission) => permissionSet.has(permission)),
    refresh
  }), [loading, error, permissionSet, refresh]);
  if (loading) return loadingFallback;
  if (error) return errorFallback ? errorFallback(error, refresh) : null;
  return /* @__PURE__ */ jsx(PermissionContext.Provider, { value, children });
}
function usePermission() {
  const context = useContext(PermissionContext);
  if (!context) throw new Error("usePermission must be used inside PermissionProvider");
  return context;
}
function isAllowed(state, required, match) {
  const permissions = typeof required === "string" ? [required] : required;
  return match === "all" ? state.hasAllPermissions(permissions) : state.hasAnyPermission(permissions);
}
function Permission({ permission, match = "all", children, fallback = null }) {
  const state = usePermission();
  return isAllowed(state, permission, match) ? children : fallback;
}
function PermissionRoute({ permission, match = "all", children, fallback, forbidden }) {
  return /* @__PURE__ */ jsx(Permission, { permission, match, fallback: forbidden ?? fallback, children });
}
function PermissionButton({ permission, match = "all", children, fallback = null, mode = "hidden" }) {
  const state = usePermission();
  const allowed = isAllowed(state, permission, match);
  if (allowed) return children;
  if (mode === "hidden") return fallback;
  if (!isValidElement(children)) return fallback;
  return cloneElement(children, {
    disabled: true,
    "aria-disabled": true,
    onClick: void 0
  });
}
function filterByPermission(items, permissionOf, state) {
  return items.filter((item) => {
    const required = permissionOf(item);
    if (!required) return true;
    return state.hasAllPermissions(typeof required === "string" ? [required] : required);
  });
}
export {
  Permission,
  PermissionButton,
  PermissionProvider,
  PermissionRoute,
  filterByPermission,
  usePermission
};
