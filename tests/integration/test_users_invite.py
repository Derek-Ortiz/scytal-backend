import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard

CONTRASENA_ADMIN = "Correcta-Caballo-42-Bateria!"
CONTRASENA_NUEVA = "Luna-Plateada-88-Vertice-3!"

@pytest.mark.asyncio
async def test_invitacion_analista_flujo_completo(client, integration_guard, monkeypatch):
    """Verifica: invitación, cambio forzado de contraseña, auditoría y gestión de roles."""
    enviado = {}
    from app.services import usuario_service

    async def _fake_send(to, asunto, texto, html=None, *, request_id=None):
        enviado["to"] = to
        for line in texto.splitlines():
            if "Contraseña temporal:" in line:
                enviado["password"] = line.split(":", 1)[1].strip()
        return True

    monkeypatch.setattr(usuario_service, "send_email", _fake_send)

    correo_admin = f"admin-{_uuid.uuid4().hex[:8]}@scytal.local"
    r = await client.post("/auth/register", json={
        "correo": correo_admin, "contrasena": CONTRASENA_ADMIN,
        "nombre_organizacion": f"Org Invitaciones {_uuid.uuid4().hex[:8]}", "slug": None,
    })
    assert r.status_code == 201, r.text

    tok = await client.post("/auth/login", json={"correo": correo_admin, "contrasena": CONTRASENA_ADMIN})
    provisional = tok.json()["provisional_access_token"]
    assert tok.json()["must_enroll_totp"] is True

    import pyotp

    from tests.conftest import codigo_totp

    enr = await client.post("/auth/totp/enroll", headers={"Authorization": f"Bearer {provisional}"})
    secreto = enr.json()["secreto_en_claro"]
    cf = await client.post("/auth/totp/confirm", headers={"Authorization": f"Bearer {provisional}"}, json={"codigo": codigo_totp(secreto)})
    assert cf.status_code == 200, cf.text

    lg = await client.post("/auth/login", json={"correo": correo_admin, "contrasena": CONTRASENA_ADMIN})
    vt = await client.post("/auth/login/verify-totp", json={
        "pending_token": lg.json()["pending_token"], "codigo": codigo_totp(secreto, siguiente=True),
    })
    admin_token = vt.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    correo_inv = f"analista-{_uuid.uuid4().hex[:8]}@scytal.local"
    r = await client.post("/users/invite", headers=admin_headers, json={"correo": correo_inv})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rol"] == "analista"
    assert body["estado"] == "pendiente_2fa"
    assert body["correo_enviado"] is True
    assert enviado["to"] == correo_inv
    assert enviado["password"]

    contrasena_temporal = enviado["password"]

    r = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": contrasena_temporal})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["must_enroll_totp"] is True
    assert data["requires_password_change"] is True
    provisional_inv = data["provisional_access_token"]

    r = await client.get("/users", headers={"Authorization": f"Bearer {provisional_inv}"})
    assert r.status_code == 403

    enr = await client.post("/auth/totp/enroll", headers={"Authorization": f"Bearer {provisional_inv}"})
    secreto_inv = enr.json()["secreto_en_claro"]
    cf = await client.post("/auth/totp/confirm", headers={"Authorization": f"Bearer {provisional_inv}"}, json={"codigo": codigo_totp(secreto_inv)})
    assert cf.status_code == 200, cf.text

    lg = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": contrasena_temporal})
    vt = await client.post("/auth/login/verify-totp", json={
        "pending_token": lg.json()["pending_token"], "codigo": codigo_totp(secreto_inv, siguiente=True),
    })
    inv_token = vt.json()["access_token"]
    inv_headers = {"Authorization": f"Bearer {inv_token}"}

    r = await client.get("/users", headers=inv_headers)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    r = await client.post("/auth/password/change", headers=inv_headers, json={
        "contrasena_actual": contrasena_temporal, "contrasena_nueva": CONTRASENA_NUEVA,
    })
    assert r.status_code == 200, r.text

    r = await client.get("/users", headers=inv_headers)
    assert r.status_code == 401

    from tests.conftest import esperar_ventana_totp
    await esperar_ventana_totp()
    lg = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": CONTRASENA_NUEVA})
    vt = await client.post("/auth/login/verify-totp", json={
        "pending_token": lg.json()["pending_token"], "codigo": codigo_totp(secreto_inv, siguiente=True),
    })
    inv_token2 = vt.json()["access_token"]
    inv_headers2 = {"Authorization": f"Bearer {inv_token2}"}

    r = await client.get("/users", headers=inv_headers2)
    assert r.status_code == 200, r.text
    correos = {u["correo"] for u in r.json()["items"]}
    assert correo_inv in correos

    r = await client.post("/users/invite", headers=inv_headers2, json={"correo": f"x-{_uuid.uuid4().hex[:6]}@scytal.local"})
    assert r.status_code == 403

    r = await client.get("/users", headers=admin_headers)
    users = {u["correo"]: u for u in r.json()["items"]}
    inv_id = users[correo_inv]["id_usuarios"]

    r = await client.patch(f"/users/{inv_id}/role", headers=admin_headers, json={"rol": "admin_organizacion"})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "admin_organizacion"

    r = await client.patch(f"/users/{inv_id}/deactivate", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False

    r = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": CONTRASENA_NUEVA})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    r = await client.post("/users/invite", headers=admin_headers, json={"correo": correo_admin})
    assert r.status_code == 409
