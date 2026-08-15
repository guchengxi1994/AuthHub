from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .api import create_app
from .application import AuthHubSettings
from .infrastructure import RedisCache


class RuntimeSettings(BaseSettings):
    """Runtime configuration with process environment taking precedence over .env."""

    model_config = SettingsConfigDict(
        env_prefix="AUTH_HUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database: str = "sqlite+pysqlite:///authhub.db"
    redis_url: str = ""
    redis_namespace: str = "authhub:"
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    module_registration_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_HUB_MODULE_REGISTRATION_KEY",
            "MCP_MANAGER_AUTH_HUB_REGISTRATION_KEY",
        ),
    )


def _cache_from_settings(settings: RuntimeSettings):
    if not settings.redis_url:
        return None
    try:
        import redis
    except ImportError as error:
        raise RuntimeError("AUTH_HUB_REDIS_URL requires the redis extra: pip install auth-hub[redis]") from error
    return RedisCache(redis.Redis.from_url(settings.redis_url), namespace=settings.redis_namespace)


def create_runtime_app(settings: Optional[RuntimeSettings] = None):
    runtime = settings or RuntimeSettings()
    return create_app(
        database_path=runtime.database,
        cache=_cache_from_settings(runtime),
        settings=AuthHubSettings(
            admin_username=runtime.admin_username,
            admin_password=runtime.admin_password,
            module_registration_key=runtime.module_registration_key or None,
        ),
    )


app = create_runtime_app()
