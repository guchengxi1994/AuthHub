import os

from .api import create_app
from .application import AuthHubSettings
from .infrastructure import RedisCache


def _cache_from_environment():
    redis_url = os.getenv("AUTH_HUB_REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis
    except ImportError as error:
        raise RuntimeError("AUTH_HUB_REDIS_URL requires the redis extra: pip install auth-hub[redis]") from error
    return RedisCache(redis.Redis.from_url(redis_url), namespace=os.getenv("AUTH_HUB_REDIS_NAMESPACE", "authhub:"))

app = create_app(
    database_path=os.getenv("AUTH_HUB_DATABASE", "authhub.db"),
    cache=_cache_from_environment(),
    settings=AuthHubSettings(
        admin_username=os.getenv("AUTH_HUB_ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("AUTH_HUB_ADMIN_PASSWORD", "change-me-now"),
    ),
)
