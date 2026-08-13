"""Small in-memory adapters for local development and tests.

They are deliberately not intended as a production database or Redis replacement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Set

from .domain.errors import ConflictError
from .domain.models import AuditEvent, ModuleDefinition, Organization, Permission, ResourceDefinition, Role, User


class InMemoryAuthHubRepository:
    def __init__(self) -> None:
        self.users: Dict[str, User] = {}
        self.organizations: Dict[str, Organization] = {}
        self.roles: Dict[str, Role] = {}
        self.permissions: Dict[str, Permission] = {}
        self.resources: Dict[str, ResourceDefinition] = {}
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
    def delete_organization(self, organization_id: str) -> None:
        self.organizations.pop(organization_id, None)
        for values in self.user_organizations.values(): values.discard(organization_id)
    def list_organizations(self) -> List[Organization]: return list(self.organizations.values())
    def get_role(self, role_id: str) -> Optional[Role]: return self.roles.get(role_id)
    def get_role_by_code(self, code: str) -> Optional[Role]: return next((r for r in self.roles.values() if r.code == code), None)
    def save_role(self, role: Role) -> Role: self.roles[role.id] = role; return role
    def delete_role(self, role_id: str) -> None:
        self.roles.pop(role_id, None); self.role_permissions.pop(role_id, None)
        for values in self.user_roles.values(): values.discard(role_id)
    def list_roles(self) -> List[Role]: return list(self.roles.values())
    def get_permission(self, code: str) -> Optional[Permission]: return self.permissions.get(code)
    def save_permission(self, permission: Permission) -> Permission: self.permissions[permission.code] = permission; return permission
    def delete_permission(self, code: str) -> None:
        self.permissions.pop(code, None)
        for values in self.role_permissions.values(): values.discard(code)
    def list_permissions(self) -> List[Permission]: return list(self.permissions.values())
    def get_resource(self, resource_id: str) -> Optional[ResourceDefinition]: return self.resources.get(resource_id)
    def save_resource(self, resource: ResourceDefinition) -> ResourceDefinition: self.resources[resource.id] = resource; return resource
    def delete_resource(self, resource_id: str) -> None: self.resources.pop(resource_id, None)
    def list_resources(self, module_id: Optional[str] = None) -> List[ResourceDefinition]: return [resource for resource in self.resources.values() if module_id is None or resource.module_id == module_id]
    def save_module(self, module: ModuleDefinition) -> ModuleDefinition: self.modules[module.id] = module; return module
    def delete_module(self, module_id: str) -> None:
        self.modules.pop(module_id, None)
        for resource_id in [resource.id for resource in self.resources.values() if resource.module_id == module_id]: self.resources.pop(resource_id, None)
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
        expires_at, value = item
        if expires_at and expires_at <= time.time(): self._values.pop(key, None); return None
        return value
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: self._values[key] = (time.time() + ttl_seconds if ttl_seconds else 0, value)
    def delete(self, key: str) -> None: self._values.pop(key, None)
    def delete_prefix(self, prefix: str) -> None:
        for key in [item for item in self._values if item.startswith(prefix)]: self._values.pop(key, None)


class RedisCache:
    """Redis adapter using a redis-py compatible client supplied by the host.

    The framework never creates or closes the client. ``redis_client`` only
    needs ``get``, ``setex``/``set``, ``delete`` and optionally ``scan_iter``.
    """

    def __init__(self, redis_client: Any, *, namespace: str = "authhub:") -> None:
        self.client = redis_client
        self.namespace = namespace

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
        keys = self.client.scan_iter(match=pattern) if hasattr(self.client, "scan_iter") else self.client.keys(pattern)
        keys = list(keys)
        if keys: self.client.delete(*keys)


class SQLiteAuthHubRepository:
    """Persistent SQLite fallback and reference Repository implementation.

    SQLite is intentionally the local fallback only. For PostgreSQL/MySQL the
    host can implement the same port using its existing SQLAlchemy session.
    """

    def __init__(self, path: str = "authhub.db") -> None:
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, display_name TEXT NOT NULL, email TEXT, enabled INTEGER NOT NULL, is_super_admin INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT, description TEXT, enabled INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(parent_id) REFERENCES organizations(id));
            CREATE TABLE IF NOT EXISTS roles (id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, enabled INTEGER NOT NULL, built_in INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS permissions (id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, module_id TEXT, description TEXT, kind TEXT NOT NULL, metadata TEXT NOT NULL, enabled INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resources (id TEXT PRIMARY KEY, resource_type TEXT NOT NULL, resource_key TEXT NOT NULL, name TEXT NOT NULL, module_id TEXT, metadata TEXT NOT NULL, UNIQUE(module_id, resource_type, resource_key));
            CREATE TABLE IF NOT EXISTS modules (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, metadata TEXT NOT NULL, permissions TEXT NOT NULL, apis TEXT NOT NULL, resources TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS user_roles (user_id TEXT NOT NULL, role_id TEXT NOT NULL, PRIMARY KEY(user_id, role_id), FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(role_id) REFERENCES roles(id));
            CREATE TABLE IF NOT EXISTS role_permissions (role_id TEXT NOT NULL, permission_code TEXT NOT NULL, PRIMARY KEY(role_id, permission_code), FOREIGN KEY(role_id) REFERENCES roles(id), FOREIGN KEY(permission_code) REFERENCES permissions(code));
            CREATE TABLE IF NOT EXISTS user_organizations (user_id TEXT NOT NULL, organization_id TEXT NOT NULL, PRIMARY KEY(user_id, organization_id), FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(organization_id) REFERENCES organizations(id));
            """)

    @staticmethod
    def _dt(value: str) -> datetime: return datetime.fromisoformat(value)
    @staticmethod
    def _user(row: sqlite3.Row) -> User: return User(row["id"], row["username"], row["password_hash"], row["display_name"], row["email"], bool(row["enabled"]), bool(row["is_super_admin"]), SQLiteAuthHubRepository._dt(row["created_at"]), SQLiteAuthHubRepository._dt(row["updated_at"]))
    @staticmethod
    def _org(row: sqlite3.Row) -> Organization: return Organization(row["id"], row["name"], row["parent_id"], row["description"], bool(row["enabled"]), SQLiteAuthHubRepository._dt(row["created_at"]), SQLiteAuthHubRepository._dt(row["updated_at"]))
    @staticmethod
    def _role(row: sqlite3.Row) -> Role: return Role(row["id"], row["code"], row["name"], row["description"], bool(row["enabled"]), bool(row["built_in"]), SQLiteAuthHubRepository._dt(row["created_at"]), SQLiteAuthHubRepository._dt(row["updated_at"]))
    @staticmethod
    def _permission(row: sqlite3.Row) -> Permission: return Permission(row["id"], row["code"], row["name"], row["module_id"], row["description"], row["kind"], json.loads(row["metadata"]), bool(row["enabled"]), SQLiteAuthHubRepository._dt(row["created_at"]), SQLiteAuthHubRepository._dt(row["updated_at"]))
    @staticmethod
    def _resource(row: sqlite3.Row) -> ResourceDefinition: return ResourceDefinition(row["id"], row["resource_type"], row["resource_key"], row["name"], row["module_id"], json.loads(row["metadata"]))
    @staticmethod
    def _module(row: sqlite3.Row) -> ModuleDefinition: return ModuleDefinition(row["id"], row["name"], row["description"], json.loads(row["metadata"]), json.loads(row["permissions"]), json.loads(row["apis"]), json.loads(row["resources"]), SQLiteAuthHubRepository._dt(row["updated_at"]))
    def get_user(self, user_id: str) -> Optional[User]:
        with self._connect() as db: row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._user(row) if row else None
    def get_user_by_username(self, username: str) -> Optional[User]:
        with self._connect() as db: row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return self._user(row) if row else None
    def save_user(self, user: User) -> User:
        with self._connect() as db: db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password_hash=excluded.password_hash,display_name=excluded.display_name,email=excluded.email,enabled=excluded.enabled,is_super_admin=excluded.is_super_admin,updated_at=excluded.updated_at", (user.id,user.username,user.password_hash,user.display_name,user.email,int(user.enabled),int(user.is_super_admin),user.created_at.isoformat(),user.updated_at.isoformat()))
        return user
    def list_users(self) -> List[User]:
        with self._connect() as db: rows = db.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [self._user(row) for row in rows]
    def get_organization(self, organization_id: str) -> Optional[Organization]:
        with self._connect() as db: row = db.execute("SELECT * FROM organizations WHERE id=?", (organization_id,)).fetchone()
        return self._org(row) if row else None
    def save_organization(self, organization: Organization) -> Organization:
        with self._connect() as db: db.execute("INSERT INTO organizations VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id,description=excluded.description,enabled=excluded.enabled,updated_at=excluded.updated_at", (organization.id,organization.name,organization.parent_id,organization.description,int(organization.enabled),organization.created_at.isoformat(),organization.updated_at.isoformat()))
        return organization
    def delete_organization(self, organization_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM user_organizations WHERE organization_id=?", (organization_id,))
            db.execute("DELETE FROM organizations WHERE id=?", (organization_id,))
    def list_organizations(self) -> List[Organization]:
        with self._connect() as db: rows = db.execute("SELECT * FROM organizations ORDER BY name").fetchall()
        return [self._org(row) for row in rows]
    def get_role(self, role_id: str) -> Optional[Role]:
        with self._connect() as db: row = db.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()
        return self._role(row) if row else None
    def get_role_by_code(self, code: str) -> Optional[Role]:
        with self._connect() as db: row = db.execute("SELECT * FROM roles WHERE code=?", (code,)).fetchone()
        return self._role(row) if row else None
    def save_role(self, role: Role) -> Role:
        with self._connect() as db: db.execute("INSERT INTO roles VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET code=excluded.code,name=excluded.name,description=excluded.description,enabled=excluded.enabled,built_in=excluded.built_in,updated_at=excluded.updated_at", (role.id,role.code,role.name,role.description,int(role.enabled),int(role.built_in),role.created_at.isoformat(),role.updated_at.isoformat()))
        return role
    def delete_role(self, role_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM user_roles WHERE role_id=?", (role_id,))
            db.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
            db.execute("DELETE FROM roles WHERE id=?", (role_id,))
    def list_roles(self) -> List[Role]:
        with self._connect() as db: rows = db.execute("SELECT * FROM roles ORDER BY code").fetchall()
        return [self._role(row) for row in rows]
    def get_permission(self, code: str) -> Optional[Permission]:
        with self._connect() as db: row = db.execute("SELECT * FROM permissions WHERE code=?", (code,)).fetchone()
        return self._permission(row) if row else None
    def save_permission(self, permission: Permission) -> Permission:
        with self._connect() as db: db.execute("INSERT INTO permissions VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,module_id=excluded.module_id,description=excluded.description,kind=excluded.kind,metadata=excluded.metadata,enabled=excluded.enabled,updated_at=excluded.updated_at", (permission.id,permission.code,permission.name,permission.module_id,permission.description,permission.kind,json.dumps(dict(permission.metadata)),int(permission.enabled),permission.created_at.isoformat(),permission.updated_at.isoformat()))
        return permission
    def delete_permission(self, code: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM role_permissions WHERE permission_code=?", (code,))
            db.execute("DELETE FROM permissions WHERE code=?", (code,))
    def list_permissions(self) -> List[Permission]:
        with self._connect() as db: rows = db.execute("SELECT * FROM permissions ORDER BY code").fetchall()
        return [self._permission(row) for row in rows]
    def get_resource(self, resource_id: str) -> Optional[ResourceDefinition]:
        with self._connect() as db: row = db.execute("SELECT * FROM resources WHERE id=?", (resource_id,)).fetchone()
        return self._resource(row) if row else None
    def save_resource(self, resource: ResourceDefinition) -> ResourceDefinition:
        with self._connect() as db: db.execute("INSERT INTO resources VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET resource_type=excluded.resource_type,resource_key=excluded.resource_key,name=excluded.name,module_id=excluded.module_id,metadata=excluded.metadata", (resource.id,resource.resource_type,resource.resource_key,resource.name,resource.module_id,json.dumps(dict(resource.metadata))))
        return resource
    def delete_resource(self, resource_id: str) -> None:
        with self._connect() as db: db.execute("DELETE FROM resources WHERE id=?", (resource_id,))
    def list_resources(self, module_id: Optional[str] = None) -> List[ResourceDefinition]:
        with self._connect() as db: rows = db.execute("SELECT * FROM resources WHERE module_id=? ORDER BY resource_type, resource_key", (module_id,)).fetchall() if module_id else db.execute("SELECT * FROM resources ORDER BY module_id, resource_type, resource_key").fetchall()
        return [self._resource(row) for row in rows]
    def save_module(self, module: ModuleDefinition) -> ModuleDefinition:
        with self._connect() as db: db.execute("INSERT INTO modules VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,metadata=excluded.metadata,permissions=excluded.permissions,apis=excluded.apis,resources=excluded.resources,updated_at=excluded.updated_at", (module.id,module.name,module.description,json.dumps(dict(module.metadata)),json.dumps(module.permissions),json.dumps(module.apis),json.dumps(module.resources),module.updated_at.isoformat()))
        return module
    def delete_module(self, module_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM resources WHERE module_id=?", (module_id,))
            db.execute("DELETE FROM modules WHERE id=?", (module_id,))
    def get_module(self, module_id: str) -> Optional[ModuleDefinition]:
        with self._connect() as db: row = db.execute("SELECT * FROM modules WHERE id=?", (module_id,)).fetchone()
        return self._module(row) if row else None
    def list_modules(self) -> List[ModuleDefinition]:
        with self._connect() as db: rows = db.execute("SELECT * FROM modules ORDER BY id").fetchall()
        return [self._module(row) for row in rows]
    def assign_role(self, user_id: str, role_id: str) -> None:
        with self._connect() as db: db.execute("INSERT OR IGNORE INTO user_roles VALUES (?,?)", (user_id, role_id))
    def remove_role(self, user_id: str, role_id: str) -> None:
        with self._connect() as db: db.execute("DELETE FROM user_roles WHERE user_id=? AND role_id=?", (user_id, role_id))
    def assign_permission(self, role_id: str, permission_code: str) -> None:
        with self._connect() as db: db.execute("INSERT OR IGNORE INTO role_permissions VALUES (?,?)", (role_id, permission_code))
    def remove_permission(self, role_id: str, permission_code: str) -> None:
        with self._connect() as db: db.execute("DELETE FROM role_permissions WHERE role_id=? AND permission_code=?", (role_id, permission_code))
    def user_role_ids(self, user_id: str) -> Set[str]:
        with self._connect() as db: rows = db.execute("SELECT role_id FROM user_roles WHERE user_id=?", (user_id,)).fetchall()
        return {row[0] for row in rows}
    def role_permission_codes(self, role_id: str) -> Set[str]:
        with self._connect() as db: rows = db.execute("SELECT permission_code FROM role_permissions WHERE role_id=?", (role_id,)).fetchall()
        return {row[0] for row in rows}
    def user_organization_ids(self, user_id: str) -> Set[str]:
        with self._connect() as db: rows = db.execute("SELECT organization_id FROM user_organizations WHERE user_id=?", (user_id,)).fetchall()
        return {row[0] for row in rows}
    def assign_organization(self, user_id: str, organization_id: str) -> None:
        with self._connect() as db: db.execute("INSERT OR IGNORE INTO user_organizations VALUES (?,?)", (user_id, organization_id))
    def remove_organization(self, user_id: str, organization_id: str) -> None:
        with self._connect() as db: db.execute("DELETE FROM user_organizations WHERE user_id=? AND organization_id=?", (user_id, organization_id))


class InMemoryAuditLog:
    def __init__(self) -> None: self.events: List[AuditEvent] = []
    def append(self, event: AuditEvent) -> None: self.events.append(event)
    def list(self, *, limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None) -> List[AuditEvent]:
        result = self.events
        if actor_id: result = [event for event in result if event.actor_id == actor_id]
        if action: result = [event for event in result if event.action == action]
        return list(reversed(result[-max(1, limit):]))


class SQLiteAuditLog:
    """Persistent audit log fallback backed by the AuthHub SQLite database."""

    def __init__(self, path: str) -> None:
        self.path = path
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, action TEXT NOT NULL, actor_id TEXT, target_type TEXT NOT NULL, target_id TEXT, outcome TEXT NOT NULL, occurred_at TEXT NOT NULL, metadata TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at ON audit_events(occurred_at DESC)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append(self, event: AuditEvent) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?)", (event.id, event.action, event.actor_id, event.target_type, event.target_id, event.outcome, event.occurred_at.isoformat(), json.dumps(dict(event.metadata), separators=(",", ":"))))

    def list(self, *, limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None) -> List[AuditEvent]:
        where, values = [], []
        if actor_id: where.append("actor_id=?"); values.append(actor_id)
        if action: where.append("action=?"); values.append(action)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as db:
            rows = db.execute(f"SELECT * FROM audit_events{clause} ORDER BY occurred_at DESC LIMIT ?", (*values, max(1, min(limit, 500)))).fetchall()
        return [AuditEvent(row["id"], row["action"], row["actor_id"], row["target_type"], row["target_id"], row["outcome"], datetime.fromisoformat(row["occurred_at"]), json.loads(row["metadata"])) for row in rows]


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
    def __init__(self, *, ttl_seconds: int = 3600, refresh_ttl_seconds: int = 2_592_000) -> None: self.ttl_seconds = ttl_seconds; self.refresh_ttl_seconds = refresh_ttl_seconds; self._tokens: Dict[str, tuple[str, float]] = {}; self._refresh: Dict[str, tuple[str, float]] = {}
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
        self._tokens = {token: item for token, item in self._tokens.items() if item[0] != user_id}
        self._refresh = {token: item for token, item in self._refresh.items() if item[0] != user_id}
    def authenticate(self, access_token: str) -> Optional[str]:
        item = self._tokens.get(access_token)
        if not item or item[1] <= time.time(): self._tokens.pop(access_token, None); return None
        return item[0]


class CacheTokenService:
    """Opaque token service backed by any Cache port, normally RedisCache.

    Raw credentials never appear in cache keys. Refresh tokens are single-use:
    a successful refresh rotates the refresh token before returning it.
    """

    def __init__(self, cache: Any, *, ttl_seconds: int = 3600, refresh_ttl_seconds: int = 2_592_000) -> None:
        self.cache, self.ttl_seconds, self.refresh_ttl_seconds = cache, ttl_seconds, refresh_ttl_seconds
    @staticmethod
    def _digest(token: str) -> str: return hashlib.sha256(token.encode("utf-8")).hexdigest()
    def _access_key(self, token: str) -> str: return f"session:access:{self._digest(token)}"
    def _refresh_key(self, token: str) -> str: return f"session:refresh:{self._digest(token)}"
    @staticmethod
    def _version_key(user_id: str) -> str: return f"session:user:{user_id}:version"
    def _version(self, user_id: str) -> int:
        value = self.cache.get(self._version_key(user_id))
        if value is None:
            self.cache.set(self._version_key(user_id), 0, self.refresh_ttl_seconds * 2)
            return 0
        return int(value)
    def _session(self, user_id: str) -> Mapping[str, Any]: return {"user_id": user_id, "version": self._version(user_id)}
    def issue(self, user: User) -> Mapping[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        payload = self._session(user.id)
        self.cache.set(self._access_key(access), payload, self.ttl_seconds)
        self.cache.set(self._refresh_key(refresh), payload, self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        payload = self.cache.get(self._refresh_key(refresh_token))
        self.cache.delete(self._refresh_key(refresh_token))
        if not self._valid_session(payload): return {}
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session = self._session(str(payload["user_id"]))
        self.cache.set(self._access_key(access), session, self.ttl_seconds)
        self.cache.set(self._refresh_key(refresh), session, self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def revoke(self, access_token: str) -> None: self.cache.delete(self._access_key(access_token))
    def revoke_user_tokens(self, user_id: str) -> None:
        self.cache.set(self._version_key(user_id), self._version(user_id) + 1, self.refresh_ttl_seconds * 2)
    def authenticate(self, access_token: str) -> Optional[str]:
        payload = self.cache.get(self._access_key(access_token))
        return str(payload["user_id"]) if self._valid_session(payload) else None
    def _valid_session(self, payload: Any) -> bool:
        return isinstance(payload, Mapping) and bool(payload.get("user_id")) and int(payload.get("version", -1)) == self._version(str(payload["user_id"]))


class SQLiteTokenService:
    """Persistent opaque-token fallback for local development and integration tests."""

    def __init__(self, path: str, *, ttl_seconds: int = 3600, refresh_ttl_seconds: int = 2_592_000) -> None:
        self.path, self.ttl_seconds, self.refresh_ttl_seconds = path, ttl_seconds, refresh_ttl_seconds
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")

    def _connect(self) -> sqlite3.Connection: return sqlite3.connect(self.path)
    @staticmethod
    def _digest(token: str) -> str: return hashlib.sha256(token.encode("utf-8")).hexdigest()
    def _save(self, token: str, user_id: str, kind: str, ttl: int) -> None:
        with self._connect() as db: db.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,0)", (self._digest(token), user_id, kind, time.time() + ttl))
    def issue(self, user: User) -> Mapping[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._save(access, user.id, "access", self.ttl_seconds); self._save(refresh, user.id, "refresh", self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        token_hash = self._digest(refresh_token)
        with self._connect() as db:
            row = db.execute("SELECT user_id FROM auth_sessions WHERE token_hash=? AND kind='refresh' AND revoked=0 AND expires_at>?", (token_hash, time.time())).fetchone()
            if not row: return {}
            db.execute("UPDATE auth_sessions SET revoked=1 WHERE token_hash=?", (token_hash,))
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._save(access, row[0], "access", self.ttl_seconds); self._save(refresh, row[0], "refresh", self.refresh_ttl_seconds)
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def revoke(self, access_token: str) -> None:
        with self._connect() as db: db.execute("UPDATE auth_sessions SET revoked=1 WHERE token_hash=?", (self._digest(access_token),))
    def revoke_user_tokens(self, user_id: str) -> None:
        with self._connect() as db: db.execute("UPDATE auth_sessions SET revoked=1 WHERE user_id=?", (user_id,))
    def authenticate(self, access_token: str) -> Optional[str]:
        with self._connect() as db: row = db.execute("SELECT user_id FROM auth_sessions WHERE token_hash=? AND kind='access' AND revoked=0 AND expires_at>?", (self._digest(access_token), time.time())).fetchone()
        return str(row[0]) if row else None
