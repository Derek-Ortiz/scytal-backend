import os

_base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://scytal:scytal_pass@db:5432/scytal")
if "@db:" in _base:
    os.environ["DATABASE_URL"] = _base.replace("@db:", "@127.0.0.1:")
_redis = os.environ.get("REDIS_URL", "redis://redis:6379/0")
if "@redis:" in _redis:
    os.environ["REDIS_URL"] = _redis.replace("@redis:", "@127.0.0.1:")

import pytest
import pytest_asyncio
import time
import pyotp
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.session import SessionLocal, engine

def codigo_totp(secreto: str, siguiente: bool = False) -> str:
    """Código TOTP de la ventana actual o de la SIGUIENTE (para evitar replay en pruebas:
    confirm y verify en la misma ventana de 30s → el segundo código se rechaza por replay)."""
    totp = pyotp.TOTP(secreto)
    if not siguiente:
        return totp.now()
    step = int(time.time() // 30) + 1
    return totp.at(step * 30)

import asyncio

async def esperar_ventana_totp() -> None:
    """Espera el inicio de la SIGUIENTE ventana de 30s (máx ~31s).
    Necesario cuando una prueba hace 3+ verificaciones TOTP: el control de replay
    (§core/security.verify_totp) rechaza cualquier paso <= ultimo_totp_step, así que
    la tercera verificación en la misma ventana SIEMPRE sería rechazada."""
    ahora = time.time()
    restante = 30 - (ahora % 30) + 1.5
    await asyncio.sleep(restante)

@pytest_asyncio.fixture
async def client():
    """Cliente HTTP in-process contra la app real (requiere DB + Redis de docker compose)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def integration_guard():
    """Salta la prueba si la BD no está accesible (compose apagado)."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("BD de integración no disponible: levanta `docker compose up db redis -d`")

@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session

@pytest.fixture(autouse=True)
def no_hibp(monkeypatch):
    """HIBP fuera de las pruebas: determinismo y sin red."""
    from app.services import hibp_service

    async def _zero(password: str) -> int:
        return 0

    monkeypatch.setattr(hibp_service, "hibp_count", _zero)
