"""Domain entities. They deliberately contain no HTTP, ORM, or Redis imports."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Set
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class User:
    id: str
    username: str
    password_hash: str
    display_name: str = ""
    email: Optional[str] = None
    enabled: bool = True
    is_super_admin: bool = False
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def with_changes(self, **changes: Any) -> "User":
        return replace(self, **changes, updated_at=utcnow())


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    parent_id: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def with_changes(self, **changes: Any) -> "Organization":
        return replace(self, **changes, updated_at=utcnow())


@dataclass(frozen=True)
class Role:
    id: str
    code: str
    name: str
    description: Optional[str] = None
    enabled: bool = True
    built_in: bool = False
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def with_changes(self, **changes: Any) -> "Role":
        return replace(self, **changes, updated_at=utcnow())


@dataclass(frozen=True)
class Permission:
    id: str
    code: str
    name: str
    module_id: Optional[str] = None
    description: Optional[str] = None
    kind: str = "operation"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def with_changes(self, **changes: Any) -> "Permission":
        return replace(self, **changes, updated_at=utcnow())


@dataclass(frozen=True)
class ResourceDefinition:
    id: str
    resource_type: str
    resource_key: str
    name: str
    module_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    name: str
    description: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    permissions: List[Mapping[str, Any]] = field(default_factory=list)
    apis: List[Mapping[str, Any]] = field(default_factory=list)
    resources: List[Mapping[str, Any]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=utcnow)

    def with_changes(self, **changes: Any) -> "ModuleDefinition":
        return replace(self, **changes, updated_at=utcnow())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "metadata": dict(self.metadata),
            "permissions": list(self.permissions),
            "apis": list(self.apis),
            "resources": list(self.resources),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    authenticated: bool
    permission: str
    user_id: Optional[str] = None
    reason: Optional[str] = None
    matched_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "allowed": self.allowed,
            "authenticated": self.authenticated,
            "permission": self.permission,
        }
        if self.user_id:
            result["user_id"] = self.user_id
        if self.reason:
            result["reason"] = self.reason
        if self.matched_by:
            result["matched_by"] = self.matched_by
        return result


@dataclass(frozen=True)
class AuditEvent:
    id: str
    action: str
    actor_id: Optional[str]
    target_type: str
    target_id: Optional[str]
    outcome: str
    occurred_at: datetime = field(default_factory=utcnow)
    metadata: Mapping[str, Any] = field(default_factory=dict)
