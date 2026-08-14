// src/index.tsx
import {
  createContext,
  cloneElement,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { jsx } from "react/jsx-runtime";
var PermissionContext = createContext(null);
var ResourcePermissionContext = createContext(null);
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
function resourceResult(value) {
  return typeof value === "boolean" ? { allowed: value } : value;
}
function resourceRequestKey(request) {
  return JSON.stringify({
    permission: request.permission,
    resourceId: request.resourceId,
    externalId: request.externalId,
    context: request.context ?? null
  });
}
function ResourcePermissionProvider({ children, checkResource, cacheKey }) {
  const cached = useRef(/* @__PURE__ */ new Map());
  const identity = useRef({ cacheKey, checkResource });
  const version = useRef(0);
  if (!Object.is(identity.current.cacheKey, cacheKey) || identity.current.checkResource !== checkResource) {
    identity.current = { cacheKey, checkResource };
    cached.current.clear();
    version.current += 1;
  }
  const cacheVersion = version.current;
  const value = useMemo(() => ({
    version: cacheVersion,
    resolve: (request, refresh = false) => {
      const key = resourceRequestKey(request);
      if (refresh || !cached.current.has(key)) {
        const pending = checkResource(request).then(resourceResult);
        cached.current.set(key, pending);
      }
      return cached.current.get(key);
    }
  }), [checkResource, cacheKey, cacheVersion]);
  return /* @__PURE__ */ jsx(ResourcePermissionContext.Provider, { value, children });
}
function useResourcePermission(request, checker) {
  const cache = useContext(ResourcePermissionContext);
  if (!checker && !cache) throw new Error("useResourcePermission requires ResourcePermissionProvider or a checker");
  const contextKey = JSON.stringify(request.context ?? null);
  const stableRequest = useMemo(() => ({ ...request, context: request.context ? { ...request.context } : void 0 }), [request.permission, request.resourceId, request.externalId, contextKey]);
  const key = resourceRequestKey(stableRequest);
  const decisionKey = `${cache ? cache.version : "direct"}:${key}`;
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [resolvedDecisionKey, setResolvedDecisionKey] = useState("");
  const execute = useCallback(async (refresh = false) => {
    setResolvedDecisionKey(decisionKey);
    setLoading(true);
    setError(null);
    try {
      const next = checker ? resourceResult(await checker(stableRequest)) : await cache.resolve(stableRequest, refresh);
      setResult(next);
    } catch (reason) {
      setResult(null);
      setError(reason instanceof Error ? reason : new Error("Unable to check AuthHub resource permission"));
    } finally {
      setLoading(false);
    }
  }, [cache, checker, decisionKey, stableRequest]);
  useEffect(() => {
    void execute();
  }, [execute]);
  const current = resolvedDecisionKey === decisionKey;
  return useMemo(() => ({
    ready: current && !loading && !error,
    loading: !current || loading,
    error,
    allowed: current && Boolean(result?.allowed),
    result: current ? result : null,
    refresh: () => execute(true)
  }), [current, loading, error, result, execute]);
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
function ResourcePermission({ request, checker, children, fallback = null, loadingFallback = null, errorFallback }) {
  const state = useResourcePermission(request, checker);
  if (state.loading) return loadingFallback;
  if (state.error) return errorFallback ? errorFallback(state.error, state.refresh) : fallback;
  return state.allowed ? children : fallback;
}
function ResourcePermissionRoute({ request, checker, children, fallback, forbidden, loadingFallback, errorFallback }) {
  return /* @__PURE__ */ jsx(ResourcePermission, { request, checker, fallback: forbidden ?? fallback, loadingFallback, errorFallback, children });
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
  ResourcePermission,
  ResourcePermissionProvider,
  ResourcePermissionRoute,
  filterByPermission,
  usePermission,
  useResourcePermission
};
