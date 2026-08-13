import {
  createContext,
  cloneElement,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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

export function filterByPermission<T>(items: readonly T[], permissionOf: (item: T) => PermissionInput | undefined, state: Pick<PermissionState, "hasAllPermissions">): T[] {
  return items.filter(item => {
    const required = permissionOf(item);
    if (!required) return true;
    return state.hasAllPermissions(typeof required === "string" ? [required] : required);
  });
}
