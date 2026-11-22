import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard

CONTRASENA = "Correcta-Caballo-42-Bateria!"

async def _registrar(client, correo: str) -> None:
    r = await client.post("/auth/register", json={
        "correo": correo, "contrasena": CONTRASENA,
        "nombre_organizacion": f"Org Login HIBP {_uuid.uuid4().hex[:8]}", "slug": None,
    })
    assert r.status_code == 201, r.text

@pytest.mark.asyncio
async def test_login_con_contrasena_filtrada_fuerza_cambio(client, integration_guard, monkeypatch, db_session):
    """§7: HIBP detecta filtración en login → cambio forzado (debe_cambiar_contrasena persistido)."""
    from app.services import hibp_service
    from sqlalchemy import select

    from app.models.usuario import Usuario

    correo = f"breach-{_uuid.uuid4().hex[:8]}@scytal.local"
    await _registrar(client, correo)

    async def _breached(password: str) -> int:
        return 12345

    monkeypatch.setattr(hibp_service, "hibp_count", _breached)

    r = await client.post("/auth/login", json={"correo": correo, "contrasena": CONTRASENA})
    assert r.status_code == 200, r.text
    assert r.json()["requires_password_change"] is True

    user = (await db_session.execute(select(Usuario).where(Usuario.correo == correo))).scalar_one()
    assert user.debe_cambiar_contrasena is True

    from app.models.auditoria import EventoAuditoria
    from sqlalchemy import func

    eventos = (await db_session.execute(
        select(func.count()).select_from(EventoAuditoria)
        .where(EventoAuditoria.detalle.like("%Contraseña filtrada detectada%"))
    )).scalar_one()
    assert eventos >= 1

@pytest.mark.asyncio
async def test_login_sin_filtracion_no_fuerza_cambio(client, integration_guard, monkeypatch):
    """Camino feliz: contraseña limpia → no se marca cambio forzado."""
    from app.services import hibp_service

    correo = f"clean-{_uuid.uuid4().hex[:8]}@scytal.local"
    await _registrar(client, correo)

    async def _clean(password: str) -> int:
        return 0

    monkeypatch.setattr(hibp_service, "hibp_count", _clean)

    r = await client.post("/auth/login", json={"correo": correo, "contrasena": CONTRASENA})
    assert r.status_code == 200, r.text
    assert r.json()["requires_password_change"] is False

@pytest.mark.asyncio
async def test_login_hibp_indisponible_no_bloquea(client, integration_guard, monkeypatch):
    """Fail-open: HIBP caído (-1) no impide el login ni fuerza el cambio."""
    from app.services import hibp_service

    correo = f"failopen-{_uuid.uuid4().hex[:8]}@scytal.local"
    await _registrar(client, correo)

    async def _down(password: str) -> int:
        return -1

    monkeypatch.setattr(hibp_service, "hibp_count", _down)

    r = await client.post("/auth/login", json={"correo": correo, "contrasena": CONTRASENA})
    assert r.status_code == 200, r.text
    assert r.json()["requires_password_change"] is False

@pytest.mark.asyncio
async def test_login_ok_y_fallido_quedan_en_auditoria(client, integration_guard, db_session):
    """§6.6: login exitoso y fallido generan fila en eventos_auditoria."""
    from sqlalchemy import select

    from app.models.auditoria import EventoAuditoria

    correo = f"auditlogin-{_uuid.uuid4().hex[:8]}@scytal.local"
    await _registrar(client, correo)

    r = await client.post("/auth/login", json={"correo": correo, "contrasena": CONTRASENA})
    assert r.status_code == 200, r.text

    r = await client.post("/auth/login", json={"correo": correo, "contrasena": "Contrase?a-Mala-99!"})
    assert r.status_code == 401, r.text

    tipos = set((await db_session.execute(
        select(EventoAuditoria.tipo).where(EventoAuditoria.detalle.like(f"%{correo}%"))
    )).scalars().all())
    assert "login_ok" in tipos
    assert "login_failed" in tipos
