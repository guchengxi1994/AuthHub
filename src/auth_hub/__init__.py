"""AuthHub: an embeddable authentication and RBAC authorization framework."""

from .version import VERSION as __version__
from .application import AuthHub, AuthHubSettings
from .domain import AuthorizationResult, ModuleDefinition, Permission, Role, User
from .infrastructure import InMemoryAuthHubRepository, InMemoryCache, InMemoryAuditLog, RedisCache
from .sqlalchemy_infrastructure import SQLAlchemyAuthHubRepository, SQLAlchemyAuditLog, SQLAlchemyTokenService

__all__ = [
    "AuthHub",
    "AuthHubSettings",
    "__version__",
    "AuthorizationResult",
    "InMemoryAuthHubRepository",
    "InMemoryAuditLog",
    "InMemoryCache",
    "RedisCache",
    "SQLAlchemyAuthHubRepository", "SQLAlchemyAuditLog", "SQLAlchemyTokenService",
    "ModuleDefinition",
    "Permission",
    "Role",
    "User",
]
