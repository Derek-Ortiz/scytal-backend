import hashlib

import httpx
import redis.asyncio as redis

from app.core.config import get_settings

_redis: redis.Redis | None = None

def _get_redis() -> redis.Redis | None:
    global _redis
    if _redis is None:
        try:
            _redis = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        except Exception:
            return None
    return _redis

LOCAL_COMMON = {
    "password", "password123", "123456", "12345678", "123456789", "qwerty", "qwerty123",
    "admin", "admin123", "letmein", "welcome", "monkey", "dragon", "111111", "123123",
}

def is_locally_common(password: str) -> bool:
    return password.lower() in LOCAL_COMMON

async def hibp_count(password: str) -> int:
    """Retorna el conteo de filtraciones, -1 si no se pudo consultar (fail-open en registro suave)."""
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    conteos = await rango(prefix)
    if conteos is None:
        return -1
    return conteos.get(suffix, 0)

async def rango(prefijo5: str) -> dict[str, int] | None:
    """Conteos de HIBP para un prefijo SHA-1 de 5 hex (k-anonimato, §4.2). None si HIBP falló."""
    prefijo = prefijo5.upper()
    r = _get_redis()
    cache_key = f"hibp:{prefijo}"
    body = None
    if r is not None:
        try:
            body = await r.get(cache_key)
        except Exception:
            pass
    if body is None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(get_settings().HIBP_API_URL + prefijo,
                                        headers={"User-Agent": "scytal-backend/1.0",
                                                 "Add-Padding": "true"})
                resp.raise_for_status()
                body = resp.text
        except Exception:
            return None
        if r is not None:
            try:
                await r.set(cache_key, body, ex=get_settings().HIBP_CACHE_TTL_SECONDS)
            except Exception:
                pass
    return _parsear_rango(body)

def _parsear_rango(body: str) -> dict[str, int]:
    conteos: dict[str, int] = {}
    for line in body.splitlines():
        parts = line.strip().split(":")
        if len(parts) == 2:
            try:
                conteos[parts[0].upper()] = int(parts[1])
            except ValueError:
                continue
    return conteos

def _count_in(body: str, suffix: str) -> int:
    return _parsear_rango(body).get(suffix.upper(), 0)
