"""SQLAlchemy-backed persistence adapters used by the default local runtime."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Set

from .domain.errors import ConflictError
from .domain.models import AuditEvent, ModuleDefinition, Organization, Permission, ResourceDefinition, ResourceInstance, ResourceInstanceGrant, Role, User


def _require_sqlalchemy() -> Dict[str, Any]:
    try:
        from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, MetaData, String, Table, UniqueConstraint, create_engine, delete, insert, select, update
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.pool import NullPool, StaticPool
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("AuthHub requires SQLAlchemy. Install auth-hub or run: pip install sqlalchemy>=2.0") from error
    return locals()


def database_url(value: str) -> str:
    if "://" in value:
        return value
    if value == ":memory:":
        return "sqlite+pysqlite:///:memory:"
    return f"sqlite+pysqlite:///{value}"


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc) if not str(value).endswith("+00:00") else datetime.fromisoformat(str(value))


class SQLAlchemyAuthHubRepository:
    def __init__(self, url_or_engine: Any = "sqlite+pysqlite:///authhub.db", *, engine: Any = None) -> None:
        sa = _require_sqlalchemy()
        self._sa = sa
        url = database_url(str(url_or_engine))
        sqlite_memory = url.endswith(":memory:")
        sqlite_file = url.startswith("sqlite") and not sqlite_memory
        engine_options = {"connect_args": {"check_same_thread": False}, "poolclass": sa["StaticPool"]} if sqlite_memory else {"poolclass": sa["NullPool"]} if sqlite_file else {}
        self.engine = engine or sa["create_engine"](url, future=True, **engine_options)
        self.metadata = sa["MetaData"]()
        c, = (sa["Column"],)
        S, B, I, D, J = sa["String"], sa["Boolean"], sa["Integer"], sa["DateTime"], sa["JSON"]
        self.users = sa["Table"]("users", self.metadata, c("id", S(64), primary_key=True), c("username", S(255), unique=True, nullable=False), c("password_hash", S(512), nullable=False), c("display_name", S(255), nullable=False), c("email", S(320)), c("enabled", B, nullable=False), c("is_super_admin", B, nullable=False), c("created_at", D(timezone=True), nullable=False), c("updated_at", D(timezone=True), nullable=False))
        self.organizations = sa["Table"]("organizations", self.metadata, c("id", S(64), primary_key=True), c("name", S(255), nullable=False), c("parent_id", S(64), sa["ForeignKey"]("organizations.id")), c("description", S(2000)), c("enabled", B, nullable=False), c("created_at", D(timezone=True), nullable=False), c("updated_at", D(timezone=True), nullable=False))
        self.roles = sa["Table"]("roles", self.metadata, c("id", S(64), primary_key=True), c("code", S(255), unique=True, nullable=False), c("name", S(255), nullable=False), c("description", S(2000)), c("enabled", B, nullable=False), c("built_in", B, nullable=False), c("created_at", D(timezone=True), nullable=False), c("updated_at", D(timezone=True), nullable=False))
        self.permissions = sa["Table"]("permissions", self.metadata, c("id", S(64), primary_key=True), c("code", S(512), unique=True, nullable=False), c("name", S(255), nullable=False), c("module_id", S(255)), c("description", S(2000)), c("kind", S(64), nullable=False), c("metadata", J, nullable=False), c("enabled", B, nullable=False), c("created_at", D(timezone=True), nullable=False), c("updated_at", D(timezone=True), nullable=False))
        self.resources = sa["Table"]("resources", self.metadata, c("id", S(255), primary_key=True), c("resource_type", S(64), nullable=False), c("resource_key", S(512), nullable=False), c("name", S(255), nullable=False), c("module_id", S(255)), c("metadata", J, nullable=False), sa["UniqueConstraint"]("module_id", "resource_type", "resource_key", name="uq_resources_module_type_key"))
        self.modules = sa["Table"]("modules", self.metadata, c("id", S(255), primary_key=True), c("name", S(255), nullable=False), c("description", S(2000)), c("metadata", J, nullable=False), c("permissions", J, nullable=False), c("apis", J, nullable=False), c("resources", J, nullable=False), c("updated_at", D(timezone=True), nullable=False))
        self.user_roles = sa["Table"]("user_roles", self.metadata, c("user_id", S(64), sa["ForeignKey"]("users.id", ondelete="CASCADE"), primary_key=True), c("role_id", S(64), sa["ForeignKey"]("roles.id", ondelete="CASCADE"), primary_key=True))
        self.role_permissions = sa["Table"]("role_permissions", self.metadata, c("role_id", S(64), sa["ForeignKey"]("roles.id", ondelete="CASCADE"), primary_key=True), c("permission_code", S(512), sa["ForeignKey"]("permissions.code", ondelete="CASCADE"), primary_key=True))
        self.user_organizations = sa["Table"]("user_organizations", self.metadata, c("user_id", S(64), sa["ForeignKey"]("users.id", ondelete="CASCADE"), primary_key=True), c("organization_id", S(64), sa["ForeignKey"]("organizations.id", ondelete="CASCADE"), primary_key=True))
        self.resource_instances = sa["Table"]("resource_instances", self.metadata, c("id", S(64), primary_key=True), c("resource_id", S(255), sa["ForeignKey"]("resources.id", ondelete="CASCADE"), nullable=False), c("external_id", S(512), nullable=False), c("owner_user_id", S(64), sa["ForeignKey"]("users.id")), c("organization_id", S(64), sa["ForeignKey"]("organizations.id")), c("metadata", J, nullable=False), c("created_at", D(timezone=True), nullable=False), c("updated_at", D(timezone=True), nullable=False), sa["UniqueConstraint"]("resource_id", "external_id", name="uq_resource_instance_external"))
        self.resource_instance_grants = sa["Table"]("resource_instance_grants", self.metadata, c("id", S(64), primary_key=True), c("resource_instance_id", S(64), sa["ForeignKey"]("resource_instances.id", ondelete="CASCADE"), nullable=False), c("user_id", S(64), sa["ForeignKey"]("users.id", ondelete="CASCADE"), nullable=False), c("permission_code", S(512), sa["ForeignKey"]("permissions.code", ondelete="CASCADE"), nullable=False), c("created_at", D(timezone=True), nullable=False), sa["UniqueConstraint"]("resource_instance_id", "user_id", "permission_code", name="uq_resource_instance_grant"))
        self.metadata.create_all(self.engine)

    def _one(self, table: Any, **where: Any) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(self._sa["select"](table).where(*[table.c[key] == value for key, value in where.items()])).mappings().first()

    def _many(self, table: Any, *criteria: Any, order_by: Any = None) -> List[Any]:
        statement = self._sa["select"](table).where(*criteria)
        if order_by is not None: statement = statement.order_by(*order_by) if isinstance(order_by, (tuple, list)) else statement.order_by(order_by)
        with self.engine.connect() as conn: return list(conn.execute(statement).mappings())

    @staticmethod
    def _user(row: Any) -> User: return User(row["id"], row["username"], row["password_hash"], row["display_name"], row["email"], bool(row["enabled"]), bool(row["is_super_admin"]), _utc(row["created_at"]), _utc(row["updated_at"]))
    @staticmethod
    def _org(row: Any) -> Organization: return Organization(row["id"], row["name"], row["parent_id"], row["description"], bool(row["enabled"]), _utc(row["created_at"]), _utc(row["updated_at"]))
    @staticmethod
    def _role(row: Any) -> Role: return Role(row["id"], row["code"], row["name"], row["description"], bool(row["enabled"]), bool(row["built_in"]), _utc(row["created_at"]), _utc(row["updated_at"]))
    @staticmethod
    def _permission(row: Any) -> Permission: return Permission(row["id"], row["code"], row["name"], row["module_id"], row["description"], row["kind"], dict(row["metadata"] or {}), bool(row["enabled"]), _utc(row["created_at"]), _utc(row["updated_at"]))
    @staticmethod
    def _resource(row: Any) -> ResourceDefinition: return ResourceDefinition(row["id"], row["resource_type"], row["resource_key"], row["name"], row["module_id"], dict(row["metadata"] or {}))
    @staticmethod
    def _instance(row: Any) -> ResourceInstance: return ResourceInstance(row["id"], row["resource_id"], row["external_id"], row["owner_user_id"], row["organization_id"], dict(row["metadata"] or {}), _utc(row["created_at"]), _utc(row["updated_at"]))
    @staticmethod
    def _grant(row: Any) -> ResourceInstanceGrant: return ResourceInstanceGrant(row["id"], row["resource_instance_id"], row["user_id"], row["permission_code"], _utc(row["created_at"]))
    @staticmethod
    def _module(row: Any) -> ModuleDefinition: return ModuleDefinition(row["id"], row["name"], row["description"], dict(row["metadata"] or {}), list(row["permissions"] or []), list(row["apis"] or []), list(row["resources"] or []), _utc(row["updated_at"]))

    def _save(self, table: Any, values: Mapping[str, Any], key: str = "id") -> None:
        with self.engine.begin() as conn:
            if conn.execute(self._sa["select"](table.c[key]).where(table.c[key] == values[key])).first(): conn.execute(self._sa["update"](table).where(table.c[key] == values[key]).values(**dict(values)))
            else: conn.execute(self._sa["insert"](table).values(**dict(values)))

    def get_user(self, user_id: str) -> Optional[User]: row = self._one(self.users, id=user_id); return self._user(row) if row else None
    def get_user_by_username(self, username: str) -> Optional[User]: row = self._one(self.users, username=username); return self._user(row) if row else None
    def save_user(self, user: User) -> User:
        try: self._save(self.users, {"id": user.id, "username": user.username, "password_hash": user.password_hash, "display_name": user.display_name, "email": user.email, "enabled": user.enabled, "is_super_admin": user.is_super_admin, "created_at": user.created_at, "updated_at": user.updated_at})
        except self._sa["IntegrityError"] as error: raise ConflictError("username already exists") from error
        return user
    def list_users(self) -> List[User]: return [self._user(row) for row in self._many(self.users, order_by=self.users.c.username)]
    def get_organization(self, organization_id: str) -> Optional[Organization]: row = self._one(self.organizations, id=organization_id); return self._org(row) if row else None
    def save_organization(self, organization: Organization) -> Organization: self._save(self.organizations, {"id": organization.id, "name": organization.name, "parent_id": organization.parent_id, "description": organization.description, "enabled": organization.enabled, "created_at": organization.created_at, "updated_at": organization.updated_at}); return organization
    def delete_organization(self, organization_id: str) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["delete"](self.user_organizations).where(self.user_organizations.c.organization_id == organization_id)); conn.execute(self._sa["delete"](self.organizations).where(self.organizations.c.id == organization_id))
    def list_organizations(self) -> List[Organization]: return [self._org(row) for row in self._many(self.organizations, order_by=self.organizations.c.name)]
    def get_role(self, role_id: str) -> Optional[Role]: row = self._one(self.roles, id=role_id); return self._role(row) if row else None
    def get_role_by_code(self, code: str) -> Optional[Role]: row = self._one(self.roles, code=code); return self._role(row) if row else None
    def save_role(self, role: Role) -> Role: self._save(self.roles, {"id": role.id, "code": role.code, "name": role.name, "description": role.description, "enabled": role.enabled, "built_in": role.built_in, "created_at": role.created_at, "updated_at": role.updated_at}); return role
    def delete_role(self, role_id: str) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["delete"](self.user_roles).where(self.user_roles.c.role_id == role_id)); conn.execute(self._sa["delete"](self.role_permissions).where(self.role_permissions.c.role_id == role_id)); conn.execute(self._sa["delete"](self.roles).where(self.roles.c.id == role_id))
    def list_roles(self) -> List[Role]: return [self._role(row) for row in self._many(self.roles, order_by=self.roles.c.code)]
    def get_permission(self, code: str) -> Optional[Permission]: row = self._one(self.permissions, code=code); return self._permission(row) if row else None
    def save_permission(self, permission: Permission) -> Permission: self._save(self.permissions, {"id": permission.id, "code": permission.code, "name": permission.name, "module_id": permission.module_id, "description": permission.description, "kind": permission.kind, "metadata": dict(permission.metadata), "enabled": permission.enabled, "created_at": permission.created_at, "updated_at": permission.updated_at}, key="code"); return permission
    def delete_permission(self, code: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(self._sa["delete"](self.role_permissions).where(self.role_permissions.c.permission_code == code))
            conn.execute(self._sa["delete"](self.resource_instance_grants).where(self.resource_instance_grants.c.permission_code == code))
            conn.execute(self._sa["delete"](self.permissions).where(self.permissions.c.code == code))
    def list_permissions(self) -> List[Permission]: return [self._permission(row) for row in self._many(self.permissions, order_by=self.permissions.c.code)]
    def get_resource(self, resource_id: str) -> Optional[ResourceDefinition]: row = self._one(self.resources, id=resource_id); return self._resource(row) if row else None
    def save_resource(self, resource: ResourceDefinition) -> ResourceDefinition:
        try: self._save(self.resources, {"id": resource.id, "resource_type": resource.resource_type, "resource_key": resource.resource_key, "name": resource.name, "module_id": resource.module_id, "metadata": dict(resource.metadata)})
        except self._sa["IntegrityError"] as error: raise ConflictError("resource already exists in this module") from error
        return resource
    def delete_resource(self, resource_id: str) -> None:
        with self.engine.begin() as conn:
            instance_ids = [row[0] for row in conn.execute(self._sa["select"](self.resource_instances.c.id).where(self.resource_instances.c.resource_id == resource_id)).all()]
            if instance_ids:
                conn.execute(self._sa["delete"](self.resource_instance_grants).where(self.resource_instance_grants.c.resource_instance_id.in_(instance_ids)))
                conn.execute(self._sa["delete"](self.resource_instances).where(self.resource_instances.c.id.in_(instance_ids)))
            conn.execute(self._sa["delete"](self.resources).where(self.resources.c.id == resource_id))
    def list_resources(self, module_id: Optional[str] = None) -> List[ResourceDefinition]: return [self._resource(row) for row in self._many(self.resources, *( [self.resources.c.module_id == module_id] if module_id else []), order_by=(self.resources.c.resource_type, self.resources.c.resource_key))]
    def get_resource_instance(self, instance_id: str) -> Optional[ResourceInstance]: row = self._one(self.resource_instances, id=instance_id); return self._instance(row) if row else None
    def get_resource_instance_by_external_id(self, resource_id: str, external_id: str) -> Optional[ResourceInstance]:
        with self.engine.connect() as conn: row = conn.execute(self._sa["select"](self.resource_instances).where(self.resource_instances.c.resource_id == resource_id, self.resource_instances.c.external_id == external_id)).mappings().first()
        return self._instance(row) if row else None
    def save_resource_instance(self, instance: ResourceInstance) -> ResourceInstance:
        try: self._save(self.resource_instances, {"id": instance.id, "resource_id": instance.resource_id, "external_id": instance.external_id, "owner_user_id": instance.owner_user_id, "organization_id": instance.organization_id, "metadata": dict(instance.metadata), "created_at": instance.created_at, "updated_at": instance.updated_at})
        except self._sa["IntegrityError"] as error: raise ConflictError("resource instance already exists") from error
        return instance
    def delete_resource_instance(self, instance_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(self._sa["delete"](self.resource_instance_grants).where(self.resource_instance_grants.c.resource_instance_id == instance_id))
            conn.execute(self._sa["delete"](self.resource_instances).where(self.resource_instances.c.id == instance_id))
    def list_resource_instances(self, resource_id: Optional[str] = None, *, owner_user_id: Optional[str] = None, organization_id: Optional[str] = None) -> List[ResourceInstance]:
        criteria = [column == value for column, value in ((self.resource_instances.c.resource_id, resource_id), (self.resource_instances.c.owner_user_id, owner_user_id), (self.resource_instances.c.organization_id, organization_id)) if value is not None]
        return [self._instance(row) for row in self._many(self.resource_instances, *criteria, order_by=self.resource_instances.c.external_id)]
    def replace_resource_instance_grants(self, resource_instance_id: str, grants: List[ResourceInstanceGrant]) -> List[ResourceInstanceGrant]:
        with self.engine.begin() as conn:
            conn.execute(self._sa["delete"](self.resource_instance_grants).where(self.resource_instance_grants.c.resource_instance_id == resource_instance_id))
            if grants:
                conn.execute(self._sa["insert"](self.resource_instance_grants), [{"id": grant.id, "resource_instance_id": grant.resource_instance_id, "user_id": grant.user_id, "permission_code": grant.permission_code, "created_at": grant.created_at} for grant in grants])
        return self.list_resource_instance_grants(resource_instance_id)
    def list_resource_instance_grants(self, resource_instance_id: str) -> List[ResourceInstanceGrant]:
        return [self._grant(row) for row in self._many(self.resource_instance_grants, self.resource_instance_grants.c.resource_instance_id == resource_instance_id, order_by=(self.resource_instance_grants.c.user_id, self.resource_instance_grants.c.permission_code))]
    def has_resource_instance_grant(self, resource_instance_id: str, user_id: str, permission_code: str) -> bool:
        return self._one(self.resource_instance_grants, resource_instance_id=resource_instance_id, user_id=user_id, permission_code=permission_code) is not None
    def save_module(self, module: ModuleDefinition) -> ModuleDefinition: self._save(self.modules, {"id": module.id, "name": module.name, "description": module.description, "metadata": dict(module.metadata), "permissions": list(module.permissions), "apis": list(module.apis), "resources": list(module.resources), "updated_at": module.updated_at}); return module
    def delete_module(self, module_id: str) -> None:
        with self.engine.begin() as conn:
            resource_ids = [row[0] for row in conn.execute(self._sa["select"](self.resources.c.id).where(self.resources.c.module_id == module_id)).all()]
            if resource_ids:
                instance_ids = [row[0] for row in conn.execute(self._sa["select"](self.resource_instances.c.id).where(self.resource_instances.c.resource_id.in_(resource_ids))).all()]
                if instance_ids: conn.execute(self._sa["delete"](self.resource_instance_grants).where(self.resource_instance_grants.c.resource_instance_id.in_(instance_ids)))
                conn.execute(self._sa["delete"](self.resource_instances).where(self.resource_instances.c.resource_id.in_(resource_ids)))
            conn.execute(self._sa["delete"](self.resources).where(self.resources.c.module_id == module_id))
            conn.execute(self._sa["delete"](self.modules).where(self.modules.c.id == module_id))
    def get_module(self, module_id: str) -> Optional[ModuleDefinition]: row = self._one(self.modules, id=module_id); return self._module(row) if row else None
    def list_modules(self) -> List[ModuleDefinition]: return [self._module(row) for row in self._many(self.modules, order_by=self.modules.c.id)]
    def assign_role(self, user_id: str, role_id: str) -> None: self._link(self.user_roles, user_id=user_id, role_id=role_id)
    def remove_role(self, user_id: str, role_id: str) -> None: self._unlink(self.user_roles, user_id=user_id, role_id=role_id)
    def assign_permission(self, role_id: str, permission_code: str) -> None: self._link(self.role_permissions, role_id=role_id, permission_code=permission_code)
    def remove_permission(self, role_id: str, permission_code: str) -> None: self._unlink(self.role_permissions, role_id=role_id, permission_code=permission_code)
    def user_role_ids(self, user_id: str) -> Set[str]: return {row[0] for row in self._values(self.user_roles.c.role_id, self.user_roles.c.user_id == user_id)}
    def role_permission_codes(self, role_id: str) -> Set[str]: return {row[0] for row in self._values(self.role_permissions.c.permission_code, self.role_permissions.c.role_id == role_id)}
    def user_organization_ids(self, user_id: str) -> Set[str]: return {row[0] for row in self._values(self.user_organizations.c.organization_id, self.user_organizations.c.user_id == user_id)}
    def assign_organization(self, user_id: str, organization_id: str) -> None: self._link(self.user_organizations, user_id=user_id, organization_id=organization_id)
    def remove_organization(self, user_id: str, organization_id: str) -> None: self._unlink(self.user_organizations, user_id=user_id, organization_id=organization_id)
    def _values(self, column: Any, *criteria: Any) -> List[Any]:
        with self.engine.connect() as conn: return conn.execute(self._sa["select"](column).where(*criteria)).all()
    def _link(self, table: Any, **values: Any) -> None:
        with self.engine.begin() as conn:
            if not conn.execute(self._sa["select"](table).where(*[table.c[k] == v for k, v in values.items()])).first(): conn.execute(self._sa["insert"](table).values(**values))
    def _unlink(self, table: Any, **values: Any) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["delete"](table).where(*[table.c[k] == v for k, v in values.items()]))


class SQLAlchemyAuditLog:
    def __init__(self, engine: Any) -> None:
        sa = _require_sqlalchemy(); self._sa = sa; self.engine = engine; self.table = sa["Table"]("audit_events", sa["MetaData"](), sa["Column"]("id", sa["String"](64), primary_key=True), sa["Column"]("action", sa["String"](255), nullable=False), sa["Column"]("actor_id", sa["String"](64)), sa["Column"]("target_type", sa["String"](64), nullable=False), sa["Column"]("target_id", sa["String"](255)), sa["Column"]("outcome", sa["String"](64), nullable=False), sa["Column"]("occurred_at", sa["DateTime"](timezone=True), nullable=False), sa["Column"]("metadata", sa["JSON"], nullable=False)); self.table.metadata.create_all(engine)
    def append(self, event: AuditEvent) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["insert"](self.table).values(id=event.id, action=event.action, actor_id=event.actor_id, target_type=event.target_type, target_id=event.target_id, outcome=event.outcome, occurred_at=event.occurred_at, metadata=dict(event.metadata)))
    def list(self, *, limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None) -> List[AuditEvent]:
        criteria = [self.table.c.actor_id == actor_id] if actor_id else []
        if action: criteria.append(self.table.c.action == action)
        with self.engine.connect() as conn: rows = conn.execute(self._sa["select"](self.table).where(*criteria).order_by(self.table.c.occurred_at.desc()).limit(max(1, min(limit, 500)))).mappings().all()
        return [AuditEvent(row["id"], row["action"], row["actor_id"], row["target_type"], row["target_id"], row["outcome"], _utc(row["occurred_at"]), dict(row["metadata"] or {})) for row in rows]


class SQLAlchemyTokenService:
    def __init__(self, engine: Any, *, ttl_seconds: int = 3600, refresh_ttl_seconds: int = 2_592_000) -> None:
        sa = _require_sqlalchemy(); self._sa = sa; self.engine = engine; self.ttl_seconds = ttl_seconds; self.refresh_ttl_seconds = refresh_ttl_seconds; self.table = sa["Table"]("auth_sessions", sa["MetaData"](), sa["Column"]("token_hash", sa["String"](128), primary_key=True), sa["Column"]("user_id", sa["String"](64), nullable=False), sa["Column"]("kind", sa["String"](16), nullable=False), sa["Column"]("expires_at", sa["Integer"], nullable=False), sa["Column"]("revoked", sa["Boolean"], nullable=False, default=False)); self.table.metadata.create_all(engine)
    @staticmethod
    def _digest(token: str) -> str: return hashlib.sha256(token.encode("utf-8")).hexdigest()
    def _save(self, token: str, user_id: str, kind: str, ttl: int) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["insert"](self.table).values(token_hash=self._digest(token), user_id=user_id, kind=kind, expires_at=int(time.time() + ttl), revoked=False))
    def issue(self, user: User) -> Mapping[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32); self._save(access, user.id, "access", self.ttl_seconds); self._save(refresh, user.id, "refresh", self.refresh_ttl_seconds); return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        now = int(time.time())
        with self.engine.begin() as conn:
            row = conn.execute(self._sa["select"](self.table.c.user_id).where(self.table.c.token_hash == self._digest(refresh_token), self.table.c.kind == "refresh", self.table.c.revoked.is_(False), self.table.c.expires_at > now)).first()
            if not row: return {}
            conn.execute(self._sa["update"](self.table).where(self.table.c.token_hash == self._digest(refresh_token)).values(revoked=True))
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32); self._save(access, row[0], "access", self.ttl_seconds); self._save(refresh, row[0], "refresh", self.refresh_ttl_seconds); return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.ttl_seconds}
    def revoke(self, access_token: str) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["update"](self.table).where(self.table.c.token_hash == self._digest(access_token)).values(revoked=True))
    def revoke_user_tokens(self, user_id: str) -> None:
        with self.engine.begin() as conn: conn.execute(self._sa["update"](self.table).where(self.table.c.user_id == user_id).values(revoked=True))
    def authenticate(self, access_token: str) -> Optional[str]:
        with self.engine.connect() as conn: row = conn.execute(self._sa["select"](self.table.c.user_id).where(self.table.c.token_hash == self._digest(access_token), self.table.c.kind == "access", self.table.c.revoked.is_(False), self.table.c.expires_at > int(time.time()))).first()
        return str(row[0]) if row else None
