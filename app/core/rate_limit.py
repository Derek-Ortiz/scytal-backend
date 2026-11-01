"""Rate limiting con Redis (§6.2). Falla abierto si Redis no está disponible."""

import redis.asyncio as redis
from app.core.config import get_settings

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        except Exception:
            return None
    return _redis_client


async def check_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Retorna True si está dentro del límite, False si lo excedió. Fail-open."""
    r = _get_redis()
    if r is None:
        return True
    try:
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, window_seconds)
        return current <= limit
    except Exception:
        return True



