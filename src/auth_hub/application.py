"""Use-case layer shared by HTTP adapters and the future Python SDK contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .domain.errors import AuthenticationError, AuthorizationError, ConflictError, NotFoundError, ValidationError
from .domain.models import AuditEvent, AuthorizationResult, ModuleDefinition, Organization, Permission, Role, User, new_id
from .infrastructure import InMemoryAuthHubRepository, InMemoryAuditLog, InMemoryCache, InMemoryTokenService, SimplePasswordHasher
from .ports.repositories import AuthHubRepository
from .ports.services import AuditLog, Cache, PasswordHasher, TokenService


@dataclass(frozen=True)
class AuthHubSettings:
    permission_cache_ttl: int = 60
    admin_username: str = "admin"
    admin_password: str = "change-me-now"


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
    def create_user(self, username: str, password: str, *, display_name: str = "", email: Optional[str] = None, enabled: bool = True) -> User:
        if not username or not password: raise ValidationError("username and password are required")
        if self.repository.get_user_by_username(username): raise ConflictError("username already exists")
        user = self.repository.save_user(User(new_id(), username, self.passwords.hash(password), display_name, email, enabled))
        self._audit("user.create", None, "user", user.id, "success")
        return user

    def update_user(self, user_id: str, *, display_name: Optional[str] = None, email: Optional[str] = None, enabled: Optional[bool] = None) -> User:
        user = self._user_or_raise(user_id)
        changes: Dict[str, Any] = {}
        if display_name is not None: changes["display_name"] = display_name
        if email is not None: changes["email"] = email
        if enabled is not None: changes["enabled"] = enabled
        user = self.repository.save_user(user.with_changes(**changes))
        self.invalidate_user_permissions(user_id)
        self._audit("user.update", None, "user", user.id, "success", {"enabled": user.enabled})
        return user

    # Keeping the record avoids orphaning audit records and role relations.
    def disable_user(self, user_id: str) -> User:
        return self.update_user(user_id, enabled=False)

    def list_users(self) -> List[User]: return self.repository.list_users()

    # -- Organization management ----------------------------------------
    def create_organization(self, name: str, *, parent_id: Optional[str] = None, description: Optional[str] = None) -> Organization:
        if not name: raise ValidationError("organization name is required")
        if parent_id:
            self._organization_or_raise(parent_id)
        organization = self.repository.save_organization(Organization(new_id(), name, parent_id, description))
        self._audit("organization.create", None, "organization", organization.id, "success")
        return organization

    def update_organization(self, organization_id: str, *, name: Optional[str] = None, parent_id: Optional[str] = None, description: Optional[str] = None, enabled: Optional[bool] = None) -> Organization:
        organization = self._organization_or_raise(organization_id)
        if parent_id == organization_id: raise ValidationError("an organization cannot be its own parent")
        if parent_id: self._organization_or_raise(parent_id)
        changes: Dict[str, Any] = {}
        if name is not None: changes["name"] = name
        if parent_id is not None: changes["parent_id"] = parent_id
        if description is not None: changes["description"] = description
        if enabled is not None: changes["enabled"] = enabled
        return self.repository.save_organization(organization.with_changes(**changes))

    def list_organizations(self) -> List[Organization]: return self.repository.list_organizations()

    def organization_tree(self) -> List[Dict[str, Any]]:
        nodes = {org.id: {**self.organization_dict(org), "children": []} for org in self.repository.list_organizations()}
        roots: List[Dict[str, Any]] = []
        for org in self.repository.list_organizations():
            node = nodes[org.id]
            if org.parent_id and org.parent_id in nodes: nodes[org.parent_id]["children"].append(node)
            else: roots.append(node)
        return roots

    def assign_organization(self, user_id: str, organization_id: str) -> None:
        self._user_or_raise(user_id); self._organization_or_raise(organization_id)
        self.repository.assign_organization(user_id, organization_id)
        self._audit("user.organization.assign", None, "organization", organization_id, "success", {"user_id": user_id})

    # -- Role / permission management -----------------------------------
    def create_role(self, code: str, name: str, *, description: Optional[str] = None) -> Role:
        if not code or not name: raise ValidationError("role code and name are required")
        if self.repository.get_role_by_code(code): raise ConflictError("role code already exists")
        role = self.repository.save_role(Role(new_id(), code, name, description))
        self._audit("role.create", None, "role", role.id, "success")
        return role

    def update_role(self, role_id: str, *, name: Optional[str] = None, description: Optional[str] = None, enabled: Optional[bool] = None) -> Role:
        role = self._role_or_raise(role_id)
        if role.built_in and enabled is False: raise ValidationError("built-in role cannot be disabled")
        changes: Dict[str, Any] = {}
        if name is not None: changes["name"] = name
        if description is not None: changes["description"] = description
        if enabled is not None: changes["enabled"] = enabled
        role = self.repository.save_role(role.with_changes(**changes))
        for user in self.repository.list_users():
            if role_id in self.repository.user_role_ids(user.id): self.invalidate_user_permissions(user.id)
        return role

    def list_roles(self) -> List[Role]: return self.repository.list_roles()
    def list_permissions(self) -> List[Permission]: return self.repository.list_permissions()

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
        if user.is_super_admin: return AuthorizationResult(True, True, permission, user.id, matched_by="system_admin")
        cache_key = f"authhub:permissions:{user.id}"
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
        codes = set()
        for role_id in self.repository.user_role_ids(user_id):
            role = self.repository.get_role(role_id)
            if role and role.enabled: codes.update(self.repository.role_permission_codes(role_id))
        return sorted(codes)

    def register_module(self, module_id: str, module_name: str, *, description: Optional[str] = None, permissions: Optional[Sequence[Mapping[str, Any]]] = None, apis: Optional[Sequence[Mapping[str, Any]]] = None, resources: Optional[Sequence[Mapping[str, Any]]] = None, metadata: Optional[Mapping[str, Any]] = None) -> ModuleDefinition:
        if not module_id or not module_name: raise ValidationError("module_id and module_name are required")
        module = ModuleDefinition(module_id, module_name, description, dict(metadata or {}), list(permissions or []), list(apis or []), list(resources or []))
        module = self.repository.save_module(module)
        for item in module.permissions:
            code = str(item.get("id") or item.get("code") or "")
            if code: self.repository.save_permission(Permission(new_id(), code, str(item.get("name") or code), module_id=module_id, description=item.get("description"), metadata=dict(item)))
        # A newly registered permission may be assigned immediately by an admin;
        # invalidate every currently known user cache because the cache port has
        # no wildcard/delete-by-prefix requirement.
        for user in self.repository.list_users(): self.invalidate_user_permissions(user.id)
        return module

    def assign_role(self, user_id: str, role_id: str) -> None:
        if not self.repository.get_user(user_id): raise NotFoundError("user", user_id)
        if not self.repository.get_role(role_id): raise NotFoundError("role", role_id)
        self.repository.assign_role(user_id, role_id); self.invalidate_user_permissions(user_id)

    def assign_permission(self, role_id: str, permission: str) -> None:
        if not self.repository.get_role(role_id): raise NotFoundError("role", role_id)
        if not self.repository.get_permission(permission): raise NotFoundError("permission", permission)
        self.repository.assign_permission(role_id, permission)
        for user in self.repository.list_users():
            if role_id in self.repository.user_role_ids(user.id): self.invalidate_user_permissions(user.id)

    def invalidate_user_permissions(self, user_id: str) -> None: self.cache.delete(f"authhub:permissions:{user_id}")

    @staticmethod
    def user_dict(user: User) -> Dict[str, Any]: return {"id": user.id, "username": user.username, "display_name": user.display_name, "email": user.email, "enabled": user.enabled, "is_super_admin": user.is_super_admin}
    @staticmethod
    def organization_dict(organization: Organization) -> Dict[str, Any]: return {"id": organization.id, "name": organization.name, "parent_id": organization.parent_id, "description": organization.description, "enabled": organization.enabled}
    @staticmethod
    def role_dict(role: Role) -> Dict[str, Any]: return {"id": role.id, "code": role.code, "name": role.name, "description": role.description, "enabled": role.enabled, "built_in": role.built_in}
    @staticmethod
    def permission_dict(permission: Permission) -> Dict[str, Any]: return {"id": permission.id, "code": permission.code, "name": permission.name, "module_id": permission.module_id, "description": permission.description, "kind": permission.kind, "enabled": permission.enabled, "metadata": dict(permission.metadata)}
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
    def _audit(self, action: str, actor_id: Optional[str], target_type: str, target_id: Optional[str], outcome: str, metadata: Optional[Mapping[str, Any]] = None) -> None: self.audit.append(AuditEvent(new_id(), action, actor_id, target_type, target_id, outcome, metadata=dict(metadata or {})))
