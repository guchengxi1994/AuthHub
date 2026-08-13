"""Use-case layer shared by HTTP adapters and the future Python SDK contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .domain.errors import AuthenticationError, AuthorizationError, ConflictError, NotFoundError, ValidationError
from .domain.models import AuditEvent, AuthorizationResult, ModuleDefinition, Organization, Permission, ResourceDefinition, Role, User, new_id
from .infrastructure import CacheTokenService, InMemoryAuthHubRepository, InMemoryAuditLog, InMemoryCache, InMemoryTokenService, SimplePasswordHasher, SQLiteAuditLog, SQLiteAuthHubRepository, SQLiteTokenService
from .ports.repositories import AuthHubRepository
from .ports.services import AuditLog, Cache, PasswordHasher, TokenService

_UNSET = object()
RESOURCE_TYPES = frozenset({"api", "entity", "mcp_server", "mcp_tool", "page", "ui_action", "ui_component", "custom"})
RESOURCE_ACTIONS = {
    "api": frozenset({"read", "create", "update", "delete", "execute", "manage"}),
    "entity": frozenset({"view", "read", "create", "update", "delete", "manage"}),
    "mcp_server": frozenset({"view", "read", "create", "update", "delete", "manage"}),
    "mcp_tool": frozenset({"view", "execute", "manage"}),
    "page": frozenset({"view", "manage"}),
    "ui_action": frozenset({"execute", "manage"}),
    "ui_component": frozenset({"view", "manage"}),
    "custom": frozenset({"view", "read", "create", "update", "delete", "execute", "manage"}),
}


def _registered_permission_code(module_id: str, permission: Mapping[str, Any]) -> str:
    code = str(permission.get("id") or permission.get("code") or "")
    if code: return code
    resource_type = str(permission.get("resource_type") or "")
    resource_key = str(permission.get("resource_key") or "")
    action = str(permission.get("action") or "")
    return f"{module_id}:{resource_type}:{resource_key}:{action}" if resource_type and resource_key and action else ""


@dataclass(frozen=True)
class AuthHubSettings:
    permission_cache_ttl: int = 60
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    module_registration_key: Optional[str] = None


class AuthHub:
    """Framework facade. Inject repository, cache, token and password adapters in production."""

    def __init__(self, repository: AuthHubRepository, cache: Cache, tokens: TokenService, passwords: PasswordHasher, audit: AuditLog, settings: AuthHubSettings = AuthHubSettings()) -> None:
        self.repository, self.cache, self.tokens, self.passwords, self.audit, self.settings = repository, cache, tokens, passwords, audit, settings

    @classmethod
    def in_memory(cls, settings: AuthHubSettings = AuthHubSettings()) -> "AuthHub":
        repository = InMemoryAuthHubRepository()
        service = cls(repository, InMemoryCache(), InMemoryTokenService(), SimplePasswordHasher(), InMemoryAuditLog(), settings)
        service.bootstrap()
        return service

    @classmethod
    def local(cls, database_path: str = "authhub.db", settings: AuthHubSettings = AuthHubSettings(), *, cache: Optional[Cache] = None) -> "AuthHub":
        """Create a locally usable instance backed by SQLite and memory cache.

        SQLite is a fallback for development/test environments, not a claim
        that AuthHub owns the production database. A host can replace the
        repository and cache independently through the normal constructor.
        """
        active_cache = cache or InMemoryCache()
        tokens: TokenService = CacheTokenService(active_cache) if cache else SQLiteTokenService(database_path)
        service = cls(SQLiteAuthHubRepository(database_path), active_cache, tokens, SimplePasswordHasher(), SQLiteAuditLog(database_path), settings)
        service.bootstrap()
        return service

    def bootstrap(self) -> User:
        existing = self.repository.get_user_by_username(self.settings.admin_username)
        if existing: return existing
        admin = User(new_id(), self.settings.admin_username, self.passwords.hash(self.settings.admin_password), self.settings.admin_username, is_super_admin=True)
        self.repository.save_user(admin)
        role = Role(new_id(), "authhub:admin", "AuthHub administrator", built_in=True)
        self.repository.save_role(role)
        self.repository.assign_role(admin.id, role.id)
        return admin

    def login(self, username: str, password: str) -> Mapping[str, Any]:
        user = self.repository.get_user_by_username(username)
        if not user or not self.passwords.verify(password, user.password_hash): raise AuthenticationError("INVALID_CREDENTIALS")
        if not user.enabled: raise AuthenticationError("USER_DISABLED")
        result = dict(self.tokens.issue(user)); result["user"] = self.user_dict(user)
        self._audit("login", user.id, "user", user.id, "success")
        return result

    # -- User management -------------------------------------------------
    def create_user(self, username: str, password: str, *, display_name: str = "", email: Optional[str] = None, enabled: bool = True, organization_ids: Optional[Sequence[str]] = None, role_ids: Optional[Sequence[str]] = None, actor_id: Optional[str] = None) -> User:
        if not username or not password: raise ValidationError("username and password are required")
        if self.repository.get_user_by_username(username): raise ConflictError("username already exists")
        organization_ids = list(dict.fromkeys(str(item) for item in (organization_ids or [])))
        role_ids = list(dict.fromkeys(str(item) for item in (role_ids or [])))
        for organization_id in organization_ids: self._organization_or_raise(organization_id)
        for role_id in role_ids: self._role_or_raise(role_id)
        user = self.repository.save_user(User(new_id(), username, self.passwords.hash(password), display_name, email, enabled))
        for organization_id in organization_ids: self.repository.assign_organization(user.id, organization_id)
        for role_id in role_ids: self.repository.assign_role(user.id, role_id)
        self._audit("user.create", actor_id, "user", user.id, "success")
        return user

    def update_user(self, user_id: str, *, display_name: Optional[str] = None, email: Optional[str] = None, enabled: Optional[bool] = None, actor_id: Optional[str] = None) -> User:
        user = self._user_or_raise(user_id)
        if enabled is False and user.is_super_admin and self._active_admin_count() <= 1:
            raise ValidationError("the last system administrator cannot be disabled")
        changes: Dict[str, Any] = {}
        if display_name is not None: changes["display_name"] = display_name
        if email is not None: changes["email"] = email
        if enabled is not None: changes["enabled"] = enabled
        user = self.repository.save_user(user.with_changes(**changes))
        self.invalidate_user_permissions(user_id)
        if enabled is False:
            self.tokens.revoke_user_tokens(user_id)
        self._audit("user.update", actor_id, "user", user.id, "success", {"enabled": user.enabled})
        return user

    # Keeping the record avoids orphaning audit records and role relations.
    def disable_user(self, user_id: str, *, actor_id: Optional[str] = None) -> User:
        return self.update_user(user_id, enabled=False, actor_id=actor_id)

    def delete_user(self, user_id: str, *, actor_id: Optional[str] = None) -> User:
        user = self._user_or_raise(user_id)
        if user.is_super_admin: raise ValidationError("system administrators cannot be deleted")
        user = self.disable_user(user_id, actor_id=actor_id)
        self._audit("user.delete", actor_id, "user", user.id, "success")
        return user

    def user_roles(self, user_id: str) -> List[Role]:
        self._user_or_raise(user_id)
        return [role for role_id in self.repository.user_role_ids(user_id) if (role := self.repository.get_role(role_id))]

    def user_organizations(self, user_id: str) -> List[Organization]:
        self._user_or_raise(user_id)
        return [org for org_id in self.repository.user_organization_ids(user_id) if (org := self.repository.get_organization(org_id))]

    def list_users(self) -> List[User]: return self.repository.list_users()

    # -- Organization management ----------------------------------------
    def create_organization(self, name: str, *, parent_id: Optional[str] = None, description: Optional[str] = None, actor_id: Optional[str] = None) -> Organization:
        if not name: raise ValidationError("organization name is required")
        if parent_id:
            self._organization_or_raise(parent_id)
        organization = self.repository.save_organization(Organization(new_id(), name, parent_id, description))
        self._audit("organization.create", actor_id, "organization", organization.id, "success")
        return organization

    def update_organization(self, organization_id: str, *, name: Optional[str] = None, parent_id: Any = _UNSET, description: Optional[str] = None, enabled: Optional[bool] = None, actor_id: Optional[str] = None) -> Organization:
        organization = self._organization_or_raise(organization_id)
        if parent_id == organization_id: raise ValidationError("an organization cannot be its own parent")
        if parent_id is not _UNSET and parent_id:
            self._organization_or_raise(parent_id)
            descendants = self._organization_descendant_ids(organization_id)
            if parent_id in descendants: raise ValidationError("an organization cannot be moved below one of its descendants")
        changes: Dict[str, Any] = {}
        if name is not None: changes["name"] = name
        if parent_id is not _UNSET: changes["parent_id"] = parent_id
        if description is not None: changes["description"] = description
        if enabled is not None: changes["enabled"] = enabled
        organization = self.repository.save_organization(organization.with_changes(**changes))
        self._audit("organization.update", actor_id, "organization", organization.id, "success")
        return organization

    def delete_organization(self, organization_id: str, *, actor_id: Optional[str] = None) -> None:
        self._organization_or_raise(organization_id)
        if any(org.parent_id == organization_id for org in self.repository.list_organizations()): raise ValidationError("an organization with children cannot be deleted")
        self.repository.delete_organization(organization_id)
        self._audit("organization.delete", actor_id, "organization", organization_id, "success")

    def list_organizations(self) -> List[Organization]: return self.repository.list_organizations()

    def organization_tree(self) -> List[Dict[str, Any]]:
        nodes = {org.id: {**self.organization_dict(org), "children": []} for org in self.repository.list_organizations()}
        roots: List[Dict[str, Any]] = []
        for org in self.repository.list_organizations():
            node = nodes[org.id]
            if org.parent_id and org.parent_id in nodes: nodes[org.parent_id]["children"].append(node)
            else: roots.append(node)
        return roots

    def assign_organization(self, user_id: str, organization_id: str, *, actor_id: Optional[str] = None) -> None:
        self._user_or_raise(user_id); self._organization_or_raise(organization_id)
        self.repository.assign_organization(user_id, organization_id)
        self._audit("user.organization.assign", actor_id, "organization", organization_id, "success", {"user_id": user_id})

    def remove_organization(self, user_id: str, organization_id: str, *, actor_id: Optional[str] = None) -> None:
        self._user_or_raise(user_id); self._organization_or_raise(organization_id)
        self.repository.remove_organization(user_id, organization_id)
        self._audit("user.organization.remove", actor_id, "organization", organization_id, "success", {"user_id": user_id})

    # -- Role / permission management -----------------------------------
    def create_role(self, code: Optional[str], name: str, *, description: Optional[str] = None, actor_id: Optional[str] = None) -> Role:
        if not name: raise ValidationError("role name is required")
        code = str(code or f"role-{new_id()}")
        if self.repository.get_role_by_code(code): raise ConflictError("role code already exists")
        role = self.repository.save_role(Role(new_id(), code, name, description))
        self._audit("role.create", actor_id, "role", role.id, "success")
        return role

    def update_role(self, role_id: str, *, name: Optional[str] = None, description: Optional[str] = None, enabled: Optional[bool] = None, actor_id: Optional[str] = None) -> Role:
        role = self._role_or_raise(role_id)
        if role.built_in and enabled is False: raise ValidationError("built-in role cannot be disabled")
        changes: Dict[str, Any] = {}
        if name is not None: changes["name"] = name
        if description is not None: changes["description"] = description
        if enabled is not None: changes["enabled"] = enabled
        role = self.repository.save_role(role.with_changes(**changes))
        for user in self.repository.list_users():
            if role_id in self.repository.user_role_ids(user.id): self.invalidate_user_permissions(user.id)
        self._audit("role.update", actor_id, "role", role.id, "success")
        return role

    def delete_role(self, role_id: str, *, actor_id: Optional[str] = None) -> None:
        role = self._role_or_raise(role_id)
        if role.built_in: raise ValidationError("built-in role cannot be deleted")
        affected = [user.id for user in self.repository.list_users() if role_id in self.repository.user_role_ids(user.id)]
        self.repository.delete_role(role_id)
        for user_id in affected: self.invalidate_user_permissions(user_id)
        self._audit("role.delete", actor_id, "role", role_id, "success")

    def list_roles(self) -> List[Role]: return self.repository.list_roles()
    def list_permissions(self) -> List[Permission]: return self.repository.list_permissions()
    def role_permissions(self, role_id: str) -> List[Permission]:
        self._role_or_raise(role_id)
        return [permission for code in self.repository.role_permission_codes(role_id) if (permission := self.repository.get_permission(code))]

    def create_permission(self, code: Optional[str], name: str, *, description: Optional[str] = None, kind: str = "operation", module_id: Optional[str] = None, resource_id: Optional[str] = None, action: Optional[str] = None, role_ids: Optional[Sequence[str]] = None, metadata: Optional[Mapping[str, Any]] = None, actor_id: Optional[str] = None) -> Permission:
        if module_id:
            self.get_module(module_id)
        role_ids = list(dict.fromkeys(str(item) for item in (role_ids or [])))
        for role_id in role_ids: self._role_or_raise(role_id)
        permission_metadata = dict(metadata or {})
        if resource_id:
            resource = self.repository.get_resource(resource_id)
            if not resource: raise NotFoundError("resource", resource_id)
            if resource.module_id != module_id: raise ValidationError("resource must belong to the selected module")
            if not action: raise ValidationError("resource permissions require an action")
            if action not in RESOURCE_ACTIONS[resource.resource_type]: raise ValidationError("action is not supported by this resource type")
            code = code or f"{module_id}:{resource.resource_type}:{resource.resource_key}:{action}"
            kind = "api" if resource.resource_type == "api" else "resource"
            permission_metadata.update({"resource_id": resource.id, "resource_type": resource.resource_type, "resource_key": resource.resource_key, "action": action})
        if not code or not name: raise ValidationError("permission code and name are required")
        if self.repository.get_permission(code): raise ConflictError("permission code already exists")
        permission = self.repository.save_permission(Permission(new_id(), code, name, module_id=module_id, description=description, kind=kind, metadata=permission_metadata))
        for role_id in role_ids: self.repository.assign_permission(role_id, permission.code)
        for user in self.repository.list_users():
            if any(role_id in self.repository.user_role_ids(user.id) for role_id in role_ids): self.invalidate_user_permissions(user.id)
        self._audit("permission.create", actor_id, "permission", code, "success")
        return permission

    def update_permission(self, code: str, *, name: Optional[str] = None, description: Optional[str] = None, enabled: Optional[bool] = None, metadata: Optional[Mapping[str, Any]] = None, actor_id: Optional[str] = None) -> Permission:
        permission = self.repository.get_permission(code)
        if not permission: raise NotFoundError("permission", code)
        changes: Dict[str, Any] = {}
        if name is not None: changes["name"] = name
        if description is not None: changes["description"] = description
        if enabled is not None: changes["enabled"] = enabled
        if metadata is not None: changes["metadata"] = dict(metadata)
        permission = self.repository.save_permission(permission.with_changes(**changes))
        for user in self.repository.list_users(): self.invalidate_user_permissions(user.id)
        self._audit("permission.update", actor_id, "permission", code, "success")
        return permission

    def create_resource(self, module_id: str, resource_type: str, resource_key: str, name: str, *, metadata: Optional[Mapping[str, Any]] = None, actor_id: Optional[str] = None) -> ResourceDefinition:
        self.get_module(module_id)
        if resource_type not in RESOURCE_TYPES: raise ValidationError("unsupported resource type")
        if not resource_key or not name: raise ValidationError("resource_key and name are required")
        if any(item.resource_type == resource_type and item.resource_key == resource_key for item in self.repository.list_resources(module_id)):
            raise ConflictError("resource already exists in this module")
        resource = self.repository.save_resource(ResourceDefinition(new_id(), resource_type, resource_key, name, module_id, dict(metadata or {})))
        self._audit("resource.create", actor_id, "resource", resource.id, "success")
        return resource

    def delete_resource(self, resource_id: str, *, actor_id: Optional[str] = None) -> None:
        resource = self.repository.get_resource(resource_id)
        if not resource: raise NotFoundError("resource", resource_id)
        if any(item.metadata.get("resource_id") == resource_id for item in self.repository.list_permissions()):
            raise ValidationError("resource is still referenced by permissions")
        self.repository.delete_resource(resource_id)
        self._audit("resource.delete", actor_id, "resource", resource_id, "success")

    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        result = self.tokens.refresh(refresh_token)
        if not result.get("access_token"): raise AuthenticationError("TOKEN_INVALID")
        return result

    def logout(self, access_token: str) -> None:
        self.tokens.revoke(access_token)

    def authenticate(self, access_token: Optional[str]) -> User:
        if not access_token: raise AuthenticationError("UNAUTHENTICATED")
        user_id = self.tokens.authenticate(access_token)
        if not user_id: raise AuthenticationError("TOKEN_INVALID")
        user = self.repository.get_user(user_id)
        if not user: raise AuthenticationError("USER_NOT_FOUND")
        if not user.enabled: raise AuthenticationError("USER_DISABLED")
        return user

    def check_permission(self, access_token: Optional[str], permission: str, *, resource: Optional[str] = None, context: Optional[Mapping[str, Any]] = None) -> AuthorizationResult:
        if not permission: raise ValidationError("permission is required")
        try: user = self.authenticate(access_token)
        except AuthenticationError as error: return AuthorizationResult(False, False, permission, reason=error.code)
        known_permission = self.repository.get_permission(permission)
        if not known_permission or not known_permission.enabled:
            return AuthorizationResult(False, True, permission, user.id, reason="PERMISSION_NOT_FOUND")
        if user.is_super_admin: return AuthorizationResult(True, True, permission, user.id, matched_by="system_admin")
        cache_key = f"permissions:{user.id}"
        permissions = self.cache.get(cache_key)
        if permissions is None:
            permissions = sorted(self.user_permissions(user.id)); self.cache.set(cache_key, permissions, self.settings.permission_cache_ttl)
        allowed = permission in permissions
        result = AuthorizationResult(allowed, True, permission, user.id, None if allowed else "PERMISSION_DENIED", "rbac" if allowed else None)
        self._audit("authorization.check", user.id, "permission", permission, "allowed" if allowed else "denied", {"resource": resource, "context": dict(context or {})})
        return result

    def check_permissions(self, access_token: Optional[str], permissions: Sequence[str], *, resource: Optional[str] = None, context: Optional[Mapping[str, Any]] = None) -> List[AuthorizationResult]:
        return [self.check_permission(access_token, permission, resource=resource, context=context) for permission in permissions]

    def user_permissions(self, user_id: str) -> List[str]:
        user = self._user_or_raise(user_id)
        if user.is_super_admin:
            return sorted(permission.code for permission in self.repository.list_permissions() if permission.enabled)
        codes = set()
        for role_id in self.repository.user_role_ids(user_id):
            role = self.repository.get_role(role_id)
            if role and role.enabled:
                codes.update(code for code in self.repository.role_permission_codes(role_id) if (permission := self.repository.get_permission(code)) and permission.enabled)
        return sorted(codes)

    def register_module(self, module_id: Optional[str], module_name: str, *, description: Optional[str] = None, permissions: Optional[Sequence[Mapping[str, Any]]] = None, apis: Optional[Sequence[Mapping[str, Any]]] = None, resources: Optional[Sequence[Mapping[str, Any]]] = None, metadata: Optional[Mapping[str, Any]] = None, actor_id: Optional[str] = None) -> ModuleDefinition:
        if not module_name: raise ValidationError("module_name is required")
        module_id = str(module_id or f"module-{new_id()}")
        resources = list(resources or [])
        registered_resource_ids = set()
        for item in resources:
            resource_type = str(item.get("resource_type") or item.get("type") or "")
            if resource_type not in RESOURCE_TYPES: raise ValidationError("unsupported resource type")
            resource_key = str(item.get("resource_key") or item.get("key") or "")
            if not resource_key: raise ValidationError("registered resources require resource_type and resource_key")
            registered_resource_ids.add(str(item.get("id") or f"{module_id}:{resource_type}:{resource_key}"))
        if len(registered_resource_ids) != len(resources): raise ValidationError("registered resources must be unique")
        previous = self.repository.get_module(module_id)
        previous_resource_ids = {
            str(item.get("id") or f"{module_id}:{item.get('resource_type') or item.get('type')}:{item.get('resource_key') or item.get('key')}")
            for item in (previous.resources if previous else [])
        }
        removed_resource_ids = previous_resource_ids - registered_resource_ids
        if any(item.metadata.get("resource_id") in removed_resource_ids for item in self.repository.list_permissions()):
            raise ValidationError("registered resource is still referenced by permissions")
        declared_resources = {
            str(item.get("id") or f"{module_id}:{item.get('resource_type') or item.get('type')}:{item.get('resource_key') or item.get('key')}"): item
            for item in resources
        }
        resources_by_key = {
            (str(item.get("resource_type") or item.get("type") or ""), str(item.get("resource_key") or item.get("key") or "")): resource_id
            for resource_id, item in declared_resources.items()
        }
        normalized_permissions: List[Mapping[str, Any]] = []
        for item in permissions or []:
            permission = dict(item)
            resource_id = str(permission.get("resource_id") or "")
            if not resource_id and permission.get("resource_key"):
                resource_id = resources_by_key.get((str(permission.get("resource_type") or ""), str(permission.get("resource_key")))) or ""
            if resource_id:
                resource = declared_resources.get(resource_id)
                if not resource: raise ValidationError("registered permission must reference a declared resource")
                resource_type = str(resource.get("resource_type") or resource.get("type") or "")
                resource_key = str(resource.get("resource_key") or resource.get("key") or "")
                action = str(permission.get("action") or "")
                if action not in RESOURCE_ACTIONS[resource_type]: raise ValidationError("action is not supported by this resource type")
                if permission.get("resource_type") and permission["resource_type"] != resource_type: raise ValidationError("registered permission resource type does not match")
                if permission.get("resource_key") and permission["resource_key"] != resource_key: raise ValidationError("registered permission resource key does not match")
                permission.update({"id": _registered_permission_code(module_id, {**permission, "resource_type": resource_type, "resource_key": resource_key, "action": action}), "resource_id": resource_id, "resource_type": resource_type, "resource_key": resource_key, "action": action})
            normalized_permissions.append(permission)
        module = ModuleDefinition(module_id, module_name, description, dict(metadata or {}), normalized_permissions, list(apis or []), resources)
        module = self.repository.save_module(module)
        new_codes = set()
        for item in module.permissions:
            code = _registered_permission_code(module_id, item)
            if code:
                new_codes.add(code)
                resource_id = str(item.get("resource_id") or "")
                resource_type = str(item.get("resource_type") or "")
                kind = "api" if resource_type == "api" else "resource" if resource_id else "operation"
                self.repository.save_permission(Permission(new_id(), code, str(item.get("name") or code), module_id=module_id, description=item.get("description"), kind=kind, metadata=dict(item)))
        if previous:
            old_codes = {_registered_permission_code(module_id, item) for item in previous.permissions}
            for code in old_codes - new_codes:
                existing = self.repository.get_permission(code)
                if existing and existing.module_id == module_id: self.repository.delete_permission(code)
        for item in module.resources:
            resource_type = str(item.get("resource_type") or item.get("type") or "")
            resource_key = str(item.get("resource_key") or item.get("key") or "")
            resource_id = str(item.get("id") or f"{module_id}:{resource_type}:{resource_key}")
            self.repository.save_resource(ResourceDefinition(resource_id, resource_type, resource_key, str(item.get("name") or resource_key), module_id, dict(item.get("metadata") or item)))
        for resource_id in previous_resource_ids - registered_resource_ids: self.repository.delete_resource(resource_id)
        # A newly registered permission may be assigned immediately by an admin;
        # invalidate every currently known user cache because the cache port has
        # no wildcard/delete-by-prefix requirement.
        for user in self.repository.list_users(): self.invalidate_user_permissions(user.id)
        self._audit("module.register", actor_id, "module", module.id, "success", {"permissions": len(module.permissions), "apis": len(module.apis), "resources": len(module.resources)})
        return module

    def list_modules(self) -> List[ModuleDefinition]: return self.repository.list_modules()
    def list_resources(self, module_id: Optional[str] = None) -> List[ResourceDefinition]: return self.repository.list_resources(module_id)
    def get_module(self, module_id: str) -> ModuleDefinition:
        module = self.repository.get_module(module_id)
        if not module: raise NotFoundError("module", module_id)
        return module
    def delete_module(self, module_id: str, *, actor_id: Optional[str] = None) -> None:
        self.get_module(module_id)
        for permission in [item for item in self.repository.list_permissions() if item.module_id == module_id]: self.repository.delete_permission(permission.code)
        self.repository.delete_module(module_id)
        for user in self.repository.list_users(): self.invalidate_user_permissions(user.id)
        self._audit("module.delete", actor_id, "module", module_id, "success")

    def assign_role(self, user_id: str, role_id: str, *, actor_id: Optional[str] = None) -> None:
        if not self.repository.get_user(user_id): raise NotFoundError("user", user_id)
        if not self.repository.get_role(role_id): raise NotFoundError("role", role_id)
        self.repository.assign_role(user_id, role_id); self.invalidate_user_permissions(user_id); self._audit("user.role.assign", actor_id, "role", role_id, "success", {"user_id": user_id})

    def remove_role(self, user_id: str, role_id: str, *, actor_id: Optional[str] = None) -> None:
        self._user_or_raise(user_id); self._role_or_raise(role_id)
        self.repository.remove_role(user_id, role_id); self.invalidate_user_permissions(user_id); self._audit("user.role.remove", actor_id, "role", role_id, "success", {"user_id": user_id})

    def assign_permission(self, role_id: str, permission: str, *, actor_id: Optional[str] = None) -> None:
        if not self.repository.get_role(role_id): raise NotFoundError("role", role_id)
        if not self.repository.get_permission(permission): raise NotFoundError("permission", permission)
        self.repository.assign_permission(role_id, permission)
        for user in self.repository.list_users():
            if role_id in self.repository.user_role_ids(user.id): self.invalidate_user_permissions(user.id)
        self._audit("role.permission.assign", actor_id, "permission", permission, "success", {"role_id": role_id})

    def remove_permission(self, role_id: str, permission: str, *, actor_id: Optional[str] = None) -> None:
        self._role_or_raise(role_id)
        if not self.repository.get_permission(permission): raise NotFoundError("permission", permission)
        self.repository.remove_permission(role_id, permission)
        for user in self.repository.list_users():
            if role_id in self.repository.user_role_ids(user.id): self.invalidate_user_permissions(user.id)
        self._audit("role.permission.remove", actor_id, "permission", permission, "success", {"role_id": role_id})

    def invalidate_user_permissions(self, user_id: str) -> None: self.cache.delete(f"permissions:{user_id}")
    def list_audit_events(self, *, limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None) -> List[AuditEvent]: return list(self.audit.list(limit=limit, actor_id=actor_id, action=action))

    def user_dict(self, user: User) -> Dict[str, Any]: return {"id": user.id, "username": user.username, "display_name": user.display_name, "email": user.email, "organization_ids": sorted(self.repository.user_organization_ids(user.id)), "role_ids": sorted(self.repository.user_role_ids(user.id)), "enabled": user.enabled, "is_super_admin": user.is_super_admin}
    @staticmethod
    def organization_dict(organization: Organization) -> Dict[str, Any]: return {"id": organization.id, "name": organization.name, "parent_id": organization.parent_id, "description": organization.description, "enabled": organization.enabled}
    @staticmethod
    def role_dict(role: Role) -> Dict[str, Any]: return {"id": role.id, "code": role.code, "name": role.name, "description": role.description, "enabled": role.enabled, "built_in": role.built_in}
    @staticmethod
    def permission_dict(permission: Permission) -> Dict[str, Any]: return {"id": permission.id, "code": permission.code, "name": permission.name, "module_id": permission.module_id, "resource_id": permission.metadata.get("resource_id"), "resource_type": permission.metadata.get("resource_type"), "resource_key": permission.metadata.get("resource_key"), "action": permission.metadata.get("action"), "description": permission.description, "kind": permission.kind, "enabled": permission.enabled, "metadata": dict(permission.metadata)}
    @staticmethod
    def resource_dict(resource: ResourceDefinition) -> Dict[str, Any]: return {"id": resource.id, "resource_type": resource.resource_type, "resource_key": resource.resource_key, "name": resource.name, "module_id": resource.module_id, "metadata": dict(resource.metadata)}
    @staticmethod
    def audit_event_dict(event: AuditEvent) -> Dict[str, Any]: return {"id": event.id, "action": event.action, "actor_id": event.actor_id, "target_type": event.target_type, "target_id": event.target_id, "outcome": event.outcome, "occurred_at": event.occurred_at.isoformat(), "metadata": dict(event.metadata)}
    def _user_or_raise(self, user_id: str) -> User:
        user = self.repository.get_user(user_id)
        if not user: raise NotFoundError("user", user_id)
        return user
    def _organization_or_raise(self, organization_id: str) -> Organization:
        organization = self.repository.get_organization(organization_id)
        if not organization: raise NotFoundError("organization", organization_id)
        return organization
    def _role_or_raise(self, role_id: str) -> Role:
        role = self.repository.get_role(role_id)
        if not role: raise NotFoundError("role", role_id)
        return role
    def _active_admin_count(self) -> int: return sum(1 for user in self.repository.list_users() if user.is_super_admin and user.enabled)
    def _organization_descendant_ids(self, organization_id: str) -> set[str]:
        children: Dict[str, List[str]] = {}
        for organization in self.repository.list_organizations():
            if organization.parent_id: children.setdefault(organization.parent_id, []).append(organization.id)
        result, pending = set(), list(children.get(organization_id, []))
        while pending:
            current = pending.pop()
            if current not in result: result.add(current); pending.extend(children.get(current, []))
        return result
    def _audit(self, action: str, actor_id: Optional[str], target_type: str, target_id: Optional[str], outcome: str, metadata: Optional[Mapping[str, Any]] = None) -> None: self.audit.append(AuditEvent(new_id(), action, actor_id, target_type, target_id, outcome, metadata=dict(metadata or {})))
