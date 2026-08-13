"""Small in-memory adapters for local development and tests.

They are deliberately not intended as a production database or Redis replacement.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, List, Mapping, Optional, Set

from .domain.errors import ConflictError
from .domain.models import AuditEvent, ModuleDefinition, Organization, Permission, Role, User


class InMemoryAuthHubRepository:
    def __init__(self) -> None:
        self.users: Dict[str, User] = {}
        self.organizations: Dict[str, Organization] = {}
        self.roles: Dict[str, Role] = {}
        self.permissions: Dict[str, Permission] = {}
        self.modules: Dict[str, ModuleDefinition] = {}
        self.user_roles: Dict[str, Set[str]] = {}
        self.role_permissions: Dict[str, Set[str]] = {}
        self.user_organizations: Dict[str, Set[str]] = {}

    def get_user(self, user_id: str) -> Optional[User]: return self.users.get(user_id)
    def get_user_by_username(self, username: str) -> Optional[User]: return next((u for u in self.users.values() if u.username == username), None)
    def save_user(self, user: User) -> User:
        existing = self.get_user_by_username(user.username)
        if existing and existing.id != user.id: raise ConflictError("username already exists")
        self.users[user.id] = user
        return user
    def list_users(self) -> List[User]: return list(self.users.values())
    def get_organization(self, organization_id: str) -> Optional[Organization]: return self.organizations.get(organization_id)
    def save_organization(self, organization: Organization) -> Organization: self.organizations[organization.id] = organization; return organization
    def list_organizations(self) -> List[Organization]: return list(self.organizations.values())
    def get_role(self, role_id: str) -> Optional[Role]: return self.roles.get(role_id)
    def get_role_by_code(self, code: str) -> Optional[Role]: return next((r for r in self.roles.values() if r.code == code), None)
    def save_role(self, role: Role) -> Role: self.roles[role.id] = role; return role
    def list_roles(self) -> List[Role]: return list(self.roles.values())
    def get_permission(self, code: str) -> Optional[Permission]: return self.permissions.get(code)
    def save_permission(self, permission: Permission) -> Permission: self.permissions[permission.code] = permission; return permission
    def list_permissions(self) -> List[Permission]: return list(self.permissions.values())
    def save_module(self, module: ModuleDefinition) -> ModuleDefinition: self.modules[module.id] = module; return module
    def get_module(self, module_id: str) -> Optional[ModuleDefinition]: return self.modules.get(module_id)
    def list_modules(self) -> List[ModuleDefinition]: return list(self.modules.values())
    def assign_role(self, user_id: str, role_id: str) -> None: self.user_roles.setdefault(user_id, set()).add(role_id)
    def assign_permission(self, role_id: str, permission_code: str) -> None: self.role_permissions.setdefault(role_id, set()).add(permission_code)
    def user_role_ids(self, user_id: str) -> Set[str]: return set(self.user_roles.get(user_id, set()))
    def role_permission_codes(self, role_id: str) -> Set[str]: return set(self.role_permissions.get(role_id, set()))
    def user_organization_ids(self, user_id: str) -> Set[str]: return set(self.user_organizations.get(user_id, set()))
    def assign_organization(self, user_id: str, organization_id: str) -> None: self.user_organizations.setdefault(user_id, set()).add(organization_id)


class InMemoryCache:
    def __init__(self) -> None: self._values: Dict[str, tuple[float, Any]] = {}
    def get(self, key: str) -> Optional[Any]:
        item = self._values.get(key)
        if not item: return None
        expires_at, value = item
        if expires_at and expires_at <= time.time(): self._values.pop(key, None); return None
        return value
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: self._values[key] = (time.time() + ttl_seconds if ttl_seconds else 0, value)
    def delete(self, key: str) -> None: self._values.pop(key, None)


class InMemoryAuditLog:
    def __init__(self) -> None: self.events: List[AuditEvent] = []
    def append(self, event: AuditEvent) -> None: self.events.append(event)


class SimplePasswordHasher:
    """Development-only PBKDF2 hasher; use Argon2/bcrypt in production adapters."""
    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return f"pbkdf2_sha256$120000${salt.hex()}${digest.hex()}"
    def verify(self, password: str, password_hash: str) -> bool:
        try:
            scheme, rounds, salt, digest = password_hash.split("$")
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
            return scheme == "pbkdf2_sha256" and hmac.compare_digest(actual, digest)
        except (ValueError, TypeError): return False


class InMemoryTokenService:
    def __init__(self, *, ttl_seconds: int = 3600) -> None: self.ttl_seconds = ttl_seconds; self._tokens: Dict[str, tuple[str, float]] = {}; self._refresh: Dict[str, str] = {}
    def issue(self, user: User) -> Mapping[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._tokens[access] = (user.id, time.time() + self.ttl_seconds); self._refresh[refresh] = user.id
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        user_id = self._refresh.get(refresh_token)
        if not user_id: return {}
        access = secrets.token_urlsafe(32); self._tokens[access] = (user_id, time.time() + self.ttl_seconds)
        return {"access_token": access, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def revoke(self, access_token: str) -> None: self._tokens.pop(access_token, None)
    def authenticate(self, access_token: str) -> Optional[str]:
        item = self._tokens.get(access_token)
        if not item or item[1] <= time.time(): self._tokens.pop(access_token, None); return None
        return item[0]

