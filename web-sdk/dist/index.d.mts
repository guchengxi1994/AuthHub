import { ReactNode } from 'react';

type PermissionInput = string | readonly string[];
type PermissionMatch = "all" | "any";
interface AuthHubPermissionSnapshot {
    permissions: readonly string[];
}
type PermissionSnapshotLoader = () => Promise<AuthHubPermissionSnapshot | readonly string[]>;
interface ResourcePermissionRequest {
    permission: string;
    resourceId: string;
    externalId: string;
    context?: Readonly<Record<string, unknown>>;
}
interface ResourcePermissionResult {
    allowed: boolean;
    authenticated?: boolean;
    reason?: string;
}
/** Calls a business-backend resource authorization endpoint, never AuthHub directly. */
type ResourcePermissionChecker = (request: ResourcePermissionRequest) => Promise<ResourcePermissionResult | boolean>;
interface PermissionProviderProps {
    children: ReactNode;
    permissions?: readonly string[];
    loadPermissions?: PermissionSnapshotLoader;
    refreshKey?: unknown;
    loadingFallback?: ReactNode;
    errorFallback?: (error: Error, refresh: () => Promise<void>) => ReactNode;
}
interface PermissionState {
    ready: boolean;
    loading: boolean;
    error: Error | null;
    permissions: ReadonlySet<string>;
    hasPermission: (permission: string) => boolean;
    hasAnyPermission: (permissions: readonly string[]) => boolean;
    hasAllPermissions: (permissions: readonly string[]) => boolean;
    refresh: () => Promise<void>;
}
declare function PermissionProvider({ children, permissions: suppliedPermissions, loadPermissions, refreshKey, loadingFallback, errorFallback, }: PermissionProviderProps): ReactNode;
declare function usePermission(): PermissionState;
interface ResourcePermissionProviderProps {
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
declare function ResourcePermissionProvider({ children, checkResource, cacheKey }: ResourcePermissionProviderProps): ReactNode;
interface ResourcePermissionState {
    ready: boolean;
    loading: boolean;
    error: Error | null;
    allowed: boolean;
    result: ResourcePermissionResult | null;
    refresh: () => Promise<void>;
}
/** Resolve a record-level decision for an API, entity, MCP Server, or MCP Tool. */
declare function useResourcePermission(request: ResourcePermissionRequest, checker?: ResourcePermissionChecker): ResourcePermissionState;
interface PermissionProps {
    permission: PermissionInput;
    match?: PermissionMatch;
    children: ReactNode;
    fallback?: ReactNode;
}
/** Render children only after the provider has loaded and permission matches. */
declare function Permission({ permission, match, children, fallback }: PermissionProps): ReactNode;
interface PermissionRouteProps extends PermissionProps {
    forbidden?: ReactNode;
}
/** A router-agnostic route guard. Pass it as the route element in React Router or similar routers. */
declare function PermissionRoute({ permission, match, children, fallback, forbidden }: PermissionRouteProps): ReactNode;
interface PermissionButtonProps extends Omit<PermissionProps, "children"> {
    children: ReactNode;
    mode?: "hidden" | "disabled";
}
/** Hide an action by default, or clone one child and disable it when unauthorized. */
declare function PermissionButton({ permission, match, children, fallback, mode }: PermissionButtonProps): ReactNode;
interface ResourcePermissionProps {
    request: ResourcePermissionRequest;
    children: ReactNode;
    checker?: ResourcePermissionChecker;
    fallback?: ReactNode;
    loadingFallback?: ReactNode;
    errorFallback?: (error: Error, refresh: () => Promise<void>) => ReactNode;
}
/** Render only after a resource-instance decision has been obtained. */
declare function ResourcePermission({ request, checker, children, fallback, loadingFallback, errorFallback }: ResourcePermissionProps): ReactNode;
interface ResourcePermissionRouteProps extends ResourcePermissionProps {
    forbidden?: ReactNode;
}
/** Router-agnostic guard for a route whose target is one concrete resource instance. */
declare function ResourcePermissionRoute({ request, checker, children, fallback, forbidden, loadingFallback, errorFallback }: ResourcePermissionRouteProps): ReactNode;
declare function filterByPermission<T>(items: readonly T[], permissionOf: (item: T) => PermissionInput | undefined, state: Pick<PermissionState, "hasAllPermissions">): T[];

export { type AuthHubPermissionSnapshot, Permission, PermissionButton, type PermissionButtonProps, type PermissionInput, type PermissionMatch, type PermissionProps, PermissionProvider, type PermissionProviderProps, PermissionRoute, type PermissionRouteProps, type PermissionSnapshotLoader, type PermissionState, ResourcePermission, type ResourcePermissionChecker, type ResourcePermissionProps, ResourcePermissionProvider, type ResourcePermissionProviderProps, type ResourcePermissionRequest, type ResourcePermissionResult, ResourcePermissionRoute, type ResourcePermissionRouteProps, type ResourcePermissionState, filterByPermission, usePermission, useResourcePermission };
