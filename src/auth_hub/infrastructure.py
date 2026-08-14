"""In-memory test adapters and the Redis cache adapter.

Persistent database, audit, and token adapters live in
``sqlalchemy_infrastructure.py``. This module deliberately contains no SQL.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, List, Mapping, Optional, Set

from .domain.errors import ConflictError
from .domain.models import AuditEvent, ModuleDefinition, Organization, Permission, ResourceDefinition, ResourceInstance, ResourceInstanceGrant, Role, User


class InMemoryAuthHubRepository:
    """Test-only repository; production persistence always uses SQLAlchemy."""

    def __init__(self) -> None:
        self.users: Dict[str, User] = {}
        self.organizations: Dict[str, Organization] = {}
        self.roles: Dict[str, Role] = {}
        self.permissions: Dict[str, Permission] = {}
        self.resources: Dict[str, ResourceDefinition] = {}
        self.resource_instances: Dict[str, ResourceInstance] = {}
        self.resource_instance_grants: Dict[tuple[str, str, str], ResourceInstanceGrant] = {}
        self.modules: Dict[str, ModuleDefinition] = {}
        self.user_roles: Dict[str, Set[str]] = {}
        self.role_permissions: Dict[str, Set[str]] = {}
        self.user_organizations: Dict[str, Set[str]] = {}

    def get_user(self, user_id: str) -> Optional[User]: return self.users.get(user_id)
    def get_user_by_username(self, username: str) -> Optional[User]: return next((item for item in self.users.values() if item.username == username), None)
    def save_user(self, user: User) -> User:
        existing = self.get_user_by_username(user.username)
        if existing and existing.id != user.id: raise ConflictError("username already exists")
        self.users[user.id] = user
        return user
    def list_users(self) -> List[User]: return list(self.users.values())
    def get_organization(self, organization_id: str) -> Optional[Organization]: return self.organizations.get(organization_id)
    def save_organization(self, organization: Organization) -> Organization: self.organizations[organization.id] = organization; return organization
    def delete_organization(self, organization_id: str) -> None:
        self.organizations.pop(organization_id, None)
        for items in self.user_organizations.values(): items.discard(organization_id)
    def list_organizations(self) -> List[Organization]: return list(self.organizations.values())
    def get_role(self, role_id: str) -> Optional[Role]: return self.roles.get(role_id)
    def get_role_by_code(self, code: str) -> Optional[Role]: return next((item for item in self.roles.values() if item.code == code), None)
    def save_role(self, role: Role) -> Role: self.roles[role.id] = role; return role
    def delete_role(self, role_id: str) -> None:
        self.roles.pop(role_id, None); self.role_permissions.pop(role_id, None)
        for items in self.user_roles.values(): items.discard(role_id)
    def list_roles(self) -> List[Role]: return list(self.roles.values())
    def get_permission(self, code: str) -> Optional[Permission]: return self.permissions.get(code)
    def save_permission(self, permission: Permission) -> Permission: self.permissions[permission.code] = permission; return permission
    def delete_permission(self, code: str) -> None:
        self.permissions.pop(code, None)
        for items in self.role_permissions.values(): items.discard(code)
        for key in [key for key in self.resource_instance_grants if key[2] == code]: self.resource_instance_grants.pop(key, None)
    def list_permissions(self) -> List[Permission]: return list(self.permissions.values())
    def get_resource(self, resource_id: str) -> Optional[ResourceDefinition]: return self.resources.get(resource_id)
    def save_resource(self, resource: ResourceDefinition) -> ResourceDefinition: self.resources[resource.id] = resource; return resource
    def delete_resource(self, resource_id: str) -> None:
        self.resources.pop(resource_id, None)
        for instance_id in [item.id for item in self.resource_instances.values() if item.resource_id == resource_id]: self.delete_resource_instance(instance_id)
    def list_resources(self, module_id: Optional[str] = None) -> List[ResourceDefinition]: return [item for item in self.resources.values() if module_id is None or item.module_id == module_id]
    def get_resource_instance(self, instance_id: str) -> Optional[ResourceInstance]: return self.resource_instances.get(instance_id)
    def get_resource_instance_by_external_id(self, resource_id: str, external_id: str) -> Optional[ResourceInstance]: return next((item for item in self.resource_instances.values() if item.resource_id == resource_id and item.external_id == external_id), None)
    def save_resource_instance(self, instance: ResourceInstance) -> ResourceInstance:
        existing = self.get_resource_instance_by_external_id(instance.resource_id, instance.external_id)
        if existing and existing.id != instance.id: raise ConflictError("resource instance already exists")
        self.resource_instances[instance.id] = instance
        return instance
    def delete_resource_instance(self, instance_id: str) -> None:
        self.resource_instances.pop(instance_id, None)
        for key in [key for key in self.resource_instance_grants if key[0] == instance_id]: self.resource_instance_grants.pop(key, None)
    def list_resource_instances(self, resource_id: Optional[str] = None, *, owner_user_id: Optional[str] = None, organization_id: Optional[str] = None) -> List[ResourceInstance]:
        return [item for item in self.resource_instances.values() if (resource_id is None or item.resource_id == resource_id) and (owner_user_id is None or item.owner_user_id == owner_user_id) and (organization_id is None or item.organization_id == organization_id)]
    def replace_resource_instance_grants(self, resource_instance_id: str, grants: List[ResourceInstanceGrant]) -> List[ResourceInstanceGrant]:
        for key in [key for key in self.resource_instance_grants if key[0] == resource_instance_id]: self.resource_instance_grants.pop(key, None)
        for grant in grants: self.resource_instance_grants[(grant.resource_instance_id, grant.user_id, grant.permission_code)] = grant
        return self.list_resource_instance_grants(resource_instance_id)
    def list_resource_instance_grants(self, resource_instance_id: str) -> List[ResourceInstanceGrant]:
        return sorted((item for item in self.resource_instance_grants.values() if item.resource_instance_id == resource_instance_id), key=lambda item: (item.user_id, item.permission_code))
    def has_resource_instance_grant(self, resource_instance_id: str, user_id: str, permission_code: str) -> bool:
        return (resource_instance_id, user_id, permission_code) in self.resource_instance_grants
    def save_module(self, module: ModuleDefinition) -> ModuleDefinition: self.modules[module.id] = module; return module
    def delete_module(self, module_id: str) -> None:
        self.modules.pop(module_id, None)
        for resource_id in [item.id for item in self.resources.values() if item.module_id == module_id]: self.delete_resource(resource_id)
    def get_module(self, module_id: str) -> Optional[ModuleDefinition]: return self.modules.get(module_id)
    def list_modules(self) -> List[ModuleDefinition]: return list(self.modules.values())
    def assign_role(self, user_id: str, role_id: str) -> None: self.user_roles.setdefault(user_id, set()).add(role_id)
    def remove_role(self, user_id: str, role_id: str) -> None: self.user_roles.setdefault(user_id, set()).discard(role_id)
    def assign_permission(self, role_id: str, permission_code: str) -> None: self.role_permissions.setdefault(role_id, set()).add(permission_code)
    def remove_permission(self, role_id: str, permission_code: str) -> None: self.role_permissions.setdefault(role_id, set()).discard(permission_code)
    def user_role_ids(self, user_id: str) -> Set[str]: return set(self.user_roles.get(user_id, set()))
    def role_permission_codes(self, role_id: str) -> Set[str]: return set(self.role_permissions.get(role_id, set()))
    def user_organization_ids(self, user_id: str) -> Set[str]: return set(self.user_organizations.get(user_id, set()))
    def assign_organization(self, user_id: str, organization_id: str) -> None: self.user_organizations.setdefault(user_id, set()).add(organization_id)
    def remove_organization(self, user_id: str, organization_id: str) -> None: self.user_organizations.setdefault(user_id, set()).discard(organization_id)


class InMemoryCache:
    def __init__(self) -> None: self._values: Dict[str, tuple[float, Any]] = {}
    def get(self, key: str) -> Optional[Any]:
        item = self._values.get(key)
        if not item: return None
        if item[0] and item[0] <= time.time(): self._values.pop(key, None); return None
        return item[1]
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: self._values[key] = (time.time() + ttl_seconds if ttl_seconds else 0, value)
    def delete(self, key: str) -> None: self._values.pop(key, None)
    def delete_prefix(self, prefix: str) -> None:
        for key in [item for item in self._values if item.startswith(prefix)]: self._values.pop(key, None)


class RedisCache:
    """Redis adapter using a redis-py compatible client supplied by the host."""

    def __init__(self, redis_client: Any, *, namespace: str = "authhub:") -> None: self.client, self.namespace = redis_client, namespace
    def _key(self, key: str) -> str: return f"{self.namespace}{key}"
    def get(self, key: str) -> Optional[Any]:
        value = self.client.get(self._key(key))
        if value is None: return None
        if isinstance(value, bytes): value = value.decode("utf-8")
        try: return json.loads(value)
        except (TypeError, ValueError): return value
    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        encoded = json.dumps(value, separators=(",", ":"))
        if ttl_seconds > 0 and hasattr(self.client, "setex"): self.client.setex(self._key(key), ttl_seconds, encoded)
        elif ttl_seconds > 0: self.client.set(self._key(key), encoded, ex=ttl_seconds)
        else: self.client.set(self._key(key), encoded)
    def delete(self, key: str) -> None: self.client.delete(self._key(key))
    def delete_prefix(self, prefix: str) -> None:
        pattern = f"{self._key(prefix)}*"
        keys = list(self.client.scan_iter(match=pattern) if hasattr(self.client, "scan_iter") else self.client.keys(pattern))
        if keys: self.client.delete(*keys)


class InMemoryAuditLog:
    def __init__(self) -> None: self.events: List[AuditEvent] = []
    def append(self, event: AuditEvent) -> None: self.events.append(event)
    def list(self, *, limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None) -> List[AuditEvent]:
        events = [event for event in self.events if (not actor_id or event.actor_id == actor_id) and (not action or event.action == action)]
        return list(reversed(events[-max(1, limit):]))


class SimplePasswordHasher:
    """Development-only PBKDF2 hasher; use Argon2/bcrypt in production."""
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
    def __init__(self, *, ttl_seconds: int = 3600, refresh_ttl_seconds: int = 2_592_000) -> None: self.ttl_seconds, self.refresh_ttl_seconds, self._tokens, self._refresh = ttl_seconds, refresh_ttl_seconds, {}, {}
    def issue(self, user: User) -> Mapping[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._tokens[access] = (user.id, time.time() + self.ttl_seconds); self._refresh[refresh] = (user.id, time.time() + self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        item = self._refresh.pop(refresh_token, None)
        if not item or item[1] <= time.time(): return {}
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._tokens[access] = (item[0], time.time() + self.ttl_seconds); self._refresh[refresh] = (item[0], time.time() + self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def revoke(self, access_token: str) -> None: self._tokens.pop(access_token, None)
    def revoke_user_tokens(self, user_id: str) -> None:
        self._tokens = {token: item for token, item in self._tokens.items() if item[0] != user_id}; self._refresh = {token: item for token, item in self._refresh.items() if item[0] != user_id}
    def authenticate(self, access_token: str) -> Optional[str]:
        item = self._tokens.get(access_token)
        if not item or item[1] <= time.time(): self._tokens.pop(access_token, None); return None
        return item[0]


class CacheTokenService:
    """Opaque token service backed by a Cache port, normally RedisCache."""
    def __init__(self, cache: Any, *, ttl_seconds: int = 3600, refresh_ttl_seconds: int = 2_592_000) -> None: self.cache, self.ttl_seconds, self.refresh_ttl_seconds = cache, ttl_seconds, refresh_ttl_seconds
    @staticmethod
    def _digest(token: str) -> str: return hashlib.sha256(token.encode("utf-8")).hexdigest()
    def _access_key(self, token: str) -> str: return f"session:access:{self._digest(token)}"
    def _refresh_key(self, token: str) -> str: return f"session:refresh:{self._digest(token)}"
    @staticmethod
    def _version_key(user_id: str) -> str: return f"session:user:{user_id}:version"
    def _version(self, user_id: str) -> int:
        value = self.cache.get(self._version_key(user_id))
        if value is None: self.cache.set(self._version_key(user_id), 0, self.refresh_ttl_seconds * 2); return 0
        return int(value)
    def _session(self, user_id: str) -> Mapping[str, Any]: return {"user_id": user_id, "version": self._version(user_id)}
    def issue(self, user: User) -> Mapping[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32); payload = self._session(user.id)
        self.cache.set(self._access_key(access), payload, self.ttl_seconds); self.cache.set(self._refresh_key(refresh), payload, self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        payload = self.cache.get(self._refresh_key(refresh_token)); self.cache.delete(self._refresh_key(refresh_token))
        if not self._valid_session(payload): return {}
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32); session = self._session(str(payload["user_id"]))
        self.cache.set(self._access_key(access), session, self.ttl_seconds); self.cache.set(self._refresh_key(refresh), session, self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def revoke(self, access_token: str) -> None: self.cache.delete(self._access_key(access_token))
    def revoke_user_tokens(self, user_id: str) -> None: self.cache.set(self._version_key(user_id), self._version(user_id) + 1, self.refresh_ttl_seconds * 2)
    def authenticate(self, access_token: str) -> Optional[str]:
        payload = self.cache.get(self._access_key(access_token)); return str(payload["user_id"]) if self._valid_session(payload) else None
    def _valid_session(self, payload: Any) -> bool: return isinstance(payload, Mapping) and bool(payload.get("user_id")) and int(payload.get("version", -1)) == self._version(str(payload["user_id"]))
