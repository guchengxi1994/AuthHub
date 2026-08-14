import {
  createContext,
  cloneElement,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type ReactElement,
} from "react";

export type PermissionInput = string | readonly string[];
export type PermissionMatch = "all" | "any";

export interface AuthHubPermissionSnapshot {
  permissions: readonly string[];
}

export type PermissionSnapshotLoader = () => Promise<AuthHubPermissionSnapshot | readonly string[]>;

export interface ResourcePermissionRequest {
  permission: string;
  resourceId: string;
  externalId: string;
  context?: Readonly<Record<string, unknown>>;
}

export interface ResourcePermissionResult {
  allowed: boolean;
  authenticated?: boolean;
  reason?: string;
}

/** Calls a business-backend resource authorization endpoint, never AuthHub directly. */
export type ResourcePermissionChecker = (request: ResourcePermissionRequest) => Promise<ResourcePermissionResult | boolean>;

export interface PermissionProviderProps {
  children: ReactNode;
  permissions?: readonly string[];
  loadPermissions?: PermissionSnapshotLoader;
  refreshKey?: unknown;
  loadingFallback?: ReactNode;
  errorFallback?: (error: Error, refresh: () => Promise<void>) => ReactNode;
}

export interface PermissionState {
  ready: boolean;
  loading: boolean;
  error: Error | null;
  permissions: ReadonlySet<string>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (permissions: readonly string[]) => boolean;
  hasAllPermissions: (permissions: readonly string[]) => boolean;
  refresh: () => Promise<void>;
}

const PermissionContext = createContext<PermissionState | null>(null);
interface ResourcePermissionCache {
  version: number;
  resolve: (request: ResourcePermissionRequest, refresh?: boolean) => Promise<ResourcePermissionResult>;
}
const ResourcePermissionContext = createContext<ResourcePermissionCache | null>(null);

function normalizeSnapshot(
  snapshot: AuthHubPermissionSnapshot | readonly string[]
): readonly string[] {
  if (Array.isArray(snapshot)) {
    return snapshot;
  }

  return (snapshot as AuthHubPermissionSnapshot).permissions;
}

export function PermissionProvider({
  children,
  permissions: suppliedPermissions,
  loadPermissions,
  refreshKey,
  loadingFallback = null,
  errorFallback,
}: PermissionProviderProps): ReactNode {
  const [loadedPermissions, setLoadedPermissions] = useState<readonly string[]>(suppliedPermissions ?? []);
  const [loading, setLoading] = useState(Boolean(loadPermissions && !suppliedPermissions));
  const [error, setError] = useState<Error | null>(null);

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
  const value = useMemo<PermissionState>(() => ({
    ready: !loading && !error,
    loading,
    error,
    permissions: permissionSet,
    hasPermission: permission => permissionSet.has(permission),
    hasAnyPermission: permissions => permissions.some(permission => permissionSet.has(permission)),
    hasAllPermissions: permissions => permissions.every(permission => permissionSet.has(permission)),
    refresh,
  }), [loading, error, permissionSet, refresh]);

  if (loading) return loadingFallback;
  if (error) return errorFallback ? errorFallback(error, refresh) : null;
  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
}

export function usePermission(): PermissionState {
  const context = useContext(PermissionContext);
  if (!context) throw new Error("usePermission must be used inside PermissionProvider");
  return context;
}

function resourceResult(value: ResourcePermissionResult | boolean): ResourcePermissionResult {
  return typeof value === "boolean" ? { allowed: value } : value;
}

function resourceRequestKey(request: ResourcePermissionRequest): string {
  return JSON.stringify({
    permission: request.permission,
    resourceId: request.resourceId,
    externalId: request.externalId,
    context: request.context ?? null,
  });
}

export interface ResourcePermissionProviderProps {
  children: ReactNode;
  checkResource: ResourcePermissionChecker;
  /** Change when the authenticated session changes to discard prior decisions. */
  cacheKey?: unknown;
}

/**
 * Shares in-flight and completed record-level decisions for one browser
 * session. The checker belongs to the business application and should proxy
 * its protected resource endpoint.
 */
export function ResourcePermissionProvider({ children, checkResource, cacheKey }: ResourcePermissionProviderProps): ReactNode {
  const cached = useRef(new Map<string, Promise<ResourcePermissionResult>>());
  const identity = useRef({ cacheKey, checkResource });
  const version = useRef(0);
  if (!Object.is(identity.current.cacheKey, cacheKey) || identity.current.checkResource !== checkResource) {
    identity.current = { cacheKey, checkResource };
    cached.current.clear();
    version.current += 1;
  }
  const cacheVersion = version.current;
  const value = useMemo<ResourcePermissionCache>(() => ({
    version: cacheVersion,
    resolve: (request, refresh = false) => {
      const key = resourceRequestKey(request);
      if (refresh || !cached.current.has(key)) {
        const pending = checkResource(request).then(resourceResult);
        cached.current.set(key, pending);
      }
      return cached.current.get(key)!;
    },
  }), [checkResource, cacheKey, cacheVersion]);
  return <ResourcePermissionContext.Provider value={value}>{children}</ResourcePermissionContext.Provider>;
}

export interface ResourcePermissionState {
  ready: boolean;
  loading: boolean;
  error: Error | null;
  allowed: boolean;
  result: ResourcePermissionResult | null;
  refresh: () => Promise<void>;
}

/** Resolve a record-level decision for an API, entity, MCP Server, or MCP Tool. */
export function useResourcePermission(request: ResourcePermissionRequest, checker?: ResourcePermissionChecker): ResourcePermissionState {
  const cache = useContext(ResourcePermissionContext);
  if (!checker && !cache) throw new Error("useResourcePermission requires ResourcePermissionProvider or a checker");
  const contextKey = JSON.stringify(request.context ?? null);
  const stableRequest = useMemo<ResourcePermissionRequest>(() => ({ ...request, context: request.context ? { ...request.context } : undefined }), [request.permission, request.resourceId, request.externalId, contextKey]);
  const key = resourceRequestKey(stableRequest);
  const decisionKey = `${cache ? cache.version : "direct"}:${key}`;
  const [result, setResult] = useState<ResourcePermissionResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [resolvedDecisionKey, setResolvedDecisionKey] = useState("");
  const execute = useCallback(async (refresh = false) => {
    setResolvedDecisionKey(decisionKey);
    setLoading(true);
    setError(null);
    try {
      const next = checker ? resourceResult(await checker(stableRequest)) : await cache!.resolve(stableRequest, refresh);
      setResult(next);
    } catch (reason) {
      setResult(null);
      setError(reason instanceof Error ? reason : new Error("Unable to check AuthHub resource permission"));
    } finally {
      setLoading(false);
    }
  }, [cache, checker, decisionKey, stableRequest]);
  useEffect(() => { void execute(); }, [execute]);
  const current = resolvedDecisionKey === decisionKey;
  return useMemo(() => ({
    ready: current && !loading && !error,
    loading: !current || loading,
    error,
    allowed: current && Boolean(result?.allowed),
    result: current ? result : null,
    refresh: () => execute(true),
  }), [current, loading, error, result, execute]);
}

function isAllowed(state: PermissionState, required: PermissionInput, match: PermissionMatch): boolean {
  const permissions = typeof required === "string" ? [required] : required;
  return match === "all" ? state.hasAllPermissions(permissions) : state.hasAnyPermission(permissions);
}

export interface PermissionProps {
  permission: PermissionInput;
  match?: PermissionMatch;
  children: ReactNode;
  fallback?: ReactNode;
}

/** Render children only after the provider has loaded and permission matches. */
export function Permission({ permission, match = "all", children, fallback = null }: PermissionProps): ReactNode {
  const state = usePermission();
  return isAllowed(state, permission, match) ? children : fallback;
}

export interface PermissionRouteProps extends PermissionProps {
  forbidden?: ReactNode;
}

/** A router-agnostic route guard. Pass it as the route element in React Router or similar routers. */
export function PermissionRoute({ permission, match = "all", children, fallback, forbidden }: PermissionRouteProps): ReactNode {
  return <Permission permission={permission} match={match} fallback={forbidden ?? fallback}>{children}</Permission>;
}

export interface PermissionButtonProps extends Omit<PermissionProps, "children"> {
  children: ReactNode;
  mode?: "hidden" | "disabled";
}

/** Hide an action by default, or clone one child and disable it when unauthorized. */
export function PermissionButton({ permission, match = "all", children, fallback = null, mode = "hidden" }: PermissionButtonProps): ReactNode {
  const state = usePermission();
  const allowed = isAllowed(state, permission, match);
  if (allowed) return children;
  if (mode === "hidden") return fallback;
  if (!isValidElement(children)) return fallback;
  return cloneElement(children as ReactElement<{ disabled?: boolean; "aria-disabled"?: boolean; onClick?: unknown }>, {
    disabled: true,
    "aria-disabled": true,
    onClick: undefined,
  });
}

export interface ResourcePermissionProps {
  request: ResourcePermissionRequest;
  children: ReactNode;
  checker?: ResourcePermissionChecker;
  fallback?: ReactNode;
  loadingFallback?: ReactNode;
  errorFallback?: (error: Error, refresh: () => Promise<void>) => ReactNode;
}

/** Render only after a resource-instance decision has been obtained. */
export function ResourcePermission({ request, checker, children, fallback = null, loadingFallback = null, errorFallback }: ResourcePermissionProps): ReactNode {
  const state = useResourcePermission(request, checker);
  if (state.loading) return loadingFallback;
  if (state.error) return errorFallback ? errorFallback(state.error, state.refresh) : fallback;
  return state.allowed ? children : fallback;
}

export interface ResourcePermissionRouteProps extends ResourcePermissionProps {
  forbidden?: ReactNode;
}

/** Router-agnostic guard for a route whose target is one concrete resource instance. */
export function ResourcePermissionRoute({ request, checker, children, fallback, forbidden, loadingFallback, errorFallback }: ResourcePermissionRouteProps): ReactNode {
  return <ResourcePermission request={request} checker={checker} fallback={forbidden ?? fallback} loadingFallback={loadingFallback} errorFallback={errorFallback}>{children}</ResourcePermission>;
}

export function filterByPermission<T>(items: readonly T[], permissionOf: (item: T) => PermissionInput | undefined, state: Pick<PermissionState, "hasAllPermissions">): T[] {
  return items.filter(item => {
    const required = permissionOf(item);
    if (!required) return true;
    return state.hasAllPermissions(typeof required === "string" ? [required] : required);
  });
}
