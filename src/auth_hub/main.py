import os
from pathlib import Path

from .api import create_app
from .application import AuthHubSettings
from .infrastructure import RedisCache


def _load_local_env() -> dict[str, str]:
    """Read a local .env for standalone development without overriding env vars."""
    candidates = (
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).resolve().parents[3] / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    )
    for path in candidates:
        if not path.is_file():
            continue
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                values[key] = value.strip("'\"")
        return values
    return {}


_DOTENV = _load_local_env()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, _DOTENV.get(name, default))


def _cache_from_environment():
    redis_url = _env("AUTH_HUB_REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis
    except ImportError as error:
        raise RuntimeError("AUTH_HUB_REDIS_URL requires the redis extra: pip install auth-hub[redis]") from error
    return RedisCache(redis.Redis.from_url(redis_url), namespace=_env("AUTH_HUB_REDIS_NAMESPACE", "authhub:"))

app = create_app(
    database_path=_env("AUTH_HUB_DATABASE", "sqlite+pysqlite:///authhub.db"),
    cache=_cache_from_environment(),
    settings=AuthHubSettings(
        admin_username=_env("AUTH_HUB_ADMIN_USERNAME", "admin"),
        admin_password=_env("AUTH_HUB_ADMIN_PASSWORD", "change-me-now"),
        # Canonical name first; the manager-specific alias keeps old .env files working.
        module_registration_key=_env(
            "AUTH_HUB_MODULE_REGISTRATION_KEY",
            _env("MCP_MANAGER_AUTH_HUB_REGISTRATION_KEY") or None,
        ) or None,
    ),
)
