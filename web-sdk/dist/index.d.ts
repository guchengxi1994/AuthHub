import { ReactNode } from 'react';

type PermissionInput = string | readonly string[];
type PermissionMatch = "all" | "any";
interface AuthHubPermissionSnapshot {
    permissions: readonly string[];
}
type PermissionSnapshotLoader = () => Promise<AuthHubPermissionSnapshot | readonly string[]>;
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
declare function filterByPermission<T>(items: readonly T[], permissionOf: (item: T) => PermissionInput | undefined, state: Pick<PermissionState, "hasAllPermissions">): T[];

export { type AuthHubPermissionSnapshot, Permission, PermissionButton, type PermissionButtonProps, type PermissionInput, type PermissionMatch, type PermissionProps, PermissionProvider, type PermissionProviderProps, PermissionRoute, type PermissionRouteProps, type PermissionSnapshotLoader, type PermissionState, filterByPermission, usePermission };
