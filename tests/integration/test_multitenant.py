"""Prueba de aislamiento multi-tenant (§6.1): org A nunca ve/lee datos de org B (403).

Requiere docker compose corriendo (db + redis en 127.0.0.1). Se salta si no hay BD.
"""
import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard  # noqa: F401 — fixture

CONTRASENA_A = "Correcta-Caballo-42-Bateria!"
CONTRASENA_B = "Torre-Azul-77-Escudo-9!"


async def _registrar_org(client, correo: str, nombre: str, slug: str, contrasena: str) -> dict:
    r = await client.post("/auth/register", json={
        "correo": correo, "contrasena": contrasena, "nombre_organizacion": nombre, "slug": slug,
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _login_provisional(client, correo: str, contrasena: str) -> str:
    r = await client.post("/auth/login", json={"correo": correo, "contrasena": contrasena})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["must_enroll_totp"] is True
    return data["provisional_access_token"]


async def _activar_2fa(client, token_provisional: str):
    import pyotp

    from tests.conftest import codigo_totp

    r = await client.post("/auth/totp/enroll", headers={"Authorization": f"Bearer {token_provisional}"})
    assert r.status_code == 200, r.text
    secreto = r.json()["secreto_en_claro"]
    r = await client.post("/auth/totp/confirm", headers={"Authorization": f"Bearer {token_provisional}"}, json={"codigo": codigo_totp(secreto)})
    assert r.status_code == 200, r.text
    return secreto


async def _tokens_completos(client, correo: str, contrasena: str, secreto: str) -> str:
    from tests.conftest import codigo_totp

    r = await client.post("/auth/login", json={"correo": correo, "contrasena": contrasena})
    assert r.status_code == 200
    pending = r.json()["pending_token"]
    # Código de la ventana SIGUIENTE: confirm ya consumió el código de la ventana actual (replay)
    codigo = codigo_totp(secreto, siguiente=True)
    r = await client.post("/auth/login/verify-totp", json={"pending_token": pending, "codigo": codigo})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_org_a_no_lee_org_b(client, integration_guard, monkeypatch):
    """El admin de la org A no puede leer ni la org B ni sus usuarios, aunque conozca el UUID."""
    import uuid as _uuid

    correo_a = f"admin-a-{_uuid.uuid4().hex[:8]}@scytal.local"
    correo_b = f"admin-b-{_uuid.uuid4().hex[:8]}@scytal.local"

    hexu = _uuid.uuid4().hex[:8]
    ra = await _registrar_org(client, correo_a, f"Org A Test {hexu}", None, CONTRASENA_A)
    rb = await _registrar_org(client, correo_b, f"Org B Test {hexu}", None, CONTRASENA_B)
    org_a_id, org_b_id = ra["org_id"], rb["org_id"]

    tok_a = await _tokens_completos(
        client, correo_a, CONTRASENA_A,
        await _activar_2fa(client, await _login_provisional(client, correo_a, CONTRASENA_A)),
    )

    headers = {"Authorization": f"Bearer {tok_a}"}

    # 1) Leer org B → 403 (aunque el UUID exista)
    r = await client.get(f"/organizations/{org_b_id}", headers=headers)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FORBIDDEN"

    # 2) Listar organizaciones (todas) → 403: solo admin_plataforma
    r = await client.get("/organizations", headers=headers)
    assert r.status_code == 403

    # 3) Editar org B → 403
    r = await client.patch(f"/organizations/{org_b_id}", headers=headers, json={"nombre": "Hacked"})
    assert r.status_code == 403

    # 4) Ver su propia org → 200 y con sus métricas
    r = await client.get(f"/organizations/{org_a_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == ra["slug"]
    assert "metricas" in r.json()

    # 5) Listar usuarios de la org A → 200 y solo contiene usuarios de la org A
    r = await client.get("/users", headers=headers)
    assert r.status_code == 200, r.text
    correos = {u["correo"] for u in r.json()["items"]}
    assert correo_a in correos
    assert correo_b not in correos


@pytest.mark.asyncio
async def test_admin_plataforma_lista_todas_las_orgs(client, integration_guard, monkeypatch):
    """Decisión #7: admin_plataforma lista todas las organizaciones con métricas."""
    from app.db.session import SessionLocal
    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.models.usuario import Usuario

    correo_p = f"plat-{__import__('uuid').uuid4().hex[:8]}@scytal.local"
    async with SessionLocal() as db:
        db.add(Usuario(org_id=None, correo=correo_p, rol="admin_plataforma",
                       hash_contrasena=hash_password(CONTRASENA_A), estado="pendiente_2fa", activo=True))
        await db.commit()

    tok_p = await _tokens_completos(
        client, correo_p, CONTRASENA_A,
        await _activar_2fa(client, await _login_provisional(client, correo_p, CONTRASENA_A)),
    )
    r = await client.get("/organizations", headers={"Authorization": f"Bearer {tok_p}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 2
    assert all("metricas" in item for item in data["items"])
