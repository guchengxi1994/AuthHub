"""Connect a Python business service to AuthHub."""

from .client import AuthHubClient, AuthHubClientError, AuthorizationDenied, ModuleManifest, PermissionSpec, ResourceSpec, PERMISSION_CATEGORY_AUTHHUB_ADMIN, PERMISSION_CATEGORY_BUSINESS_DATA, PERMISSION_CATEGORY_BUSINESS_OPERATION, resource_permission_category
from .fastapi import AuthHubFastAPI, require_permission, require_resource_permission

try:
    from .sqlalchemy import AuthHubOutbox, AuthHubOutboxDispatcher, DispatchResult, dispatch_pending, install_after_commit_dispatcher, track_resource_instance, untrack_resource_instance
except RuntimeError:  # SQLAlchemy is an optional SDK integration dependency.
    pass

__all__ = ["AuthHubClient", "AuthHubClientError", "AuthorizationDenied", "AuthHubFastAPI", "ModuleManifest", "PermissionSpec", "ResourceSpec", "PERMISSION_CATEGORY_AUTHHUB_ADMIN", "PERMISSION_CATEGORY_BUSINESS_DATA", "PERMISSION_CATEGORY_BUSINESS_OPERATION", "resource_permission_category", "require_permission", "require_resource_permission", "AuthHubOutbox", "AuthHubOutboxDispatcher", "DispatchResult", "dispatch_pending", "install_after_commit_dispatcher", "track_resource_instance", "untrack_resource_instance"]
