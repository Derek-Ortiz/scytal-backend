"""Flujo completo de invitación de analista (§4.4 + decisión #11):

invite → login con contraseña temporal (must_enroll + requires_password_change) → enroll/confirm 2FA
→ login normal → rutas de negocio 403 PASSWORD_CHANGE_REQUIRED → password/change → acceso OK.
"""
import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard  # noqa: F401 — fixture

CONTRASENA_ADMIN = "Correcta-Caballo-42-Bateria!"
CONTRASENA_NUEVA = "Luna-Plateada-88-Vertice-3!"


@pytest.mark.asyncio
async def test_invitacion_analista_flujo_completo(client, integration_guard, monkeypatch):
    """Verifica: invitación, cambio forzado de contraseña, auditoría y gestión de roles."""
    enviado = {}
    from app.services import usuario_service

    async def _fake_send(to, asunto, texto, html=None, *, request_id=None):
        enviado["to"] = to
        # Extraer la contraseña temporal del cuerpo del correo para simular al invitado
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

    # ---- Invitar analista ----
    correo_inv = f"analista-{_uuid.uuid4().hex[:8]}@scytal.local"
    r = await client.post("/users/invite", headers=admin_headers, json={"correo": correo_inv})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rol"] == "analista"
    assert body["estado"] == "pendiente_2fa"
    assert body["correo_enviado"] is True
    assert enviado["to"] == correo_inv
    assert enviado["password"]  # el correo contiene la contraseña temporal

    contrasena_temporal = enviado["password"]

    # ---- Primer login del invitado: no entrega JWT full, pide enroll + cambio ----
    r = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": contrasena_temporal})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["must_enroll_totp"] is True
    assert data["requires_password_change"] is True
    provisional_inv = data["provisional_access_token"]

    # El invitado no puede usar rutas de negocio con el token provisional
    r = await client.get("/users", headers={"Authorization": f"Bearer {provisional_inv}"})
    assert r.status_code == 403

    # ---- Enroll + confirm del 2FA del invitado ----
    enr = await client.post("/auth/totp/enroll", headers={"Authorization": f"Bearer {provisional_inv}"})
    secreto_inv = enr.json()["secreto_en_claro"]
    cf = await client.post("/auth/totp/confirm", headers={"Authorization": f"Bearer {provisional_inv}"}, json={"codigo": codigo_totp(secreto_inv)})
    assert cf.status_code == 200, cf.text

    # ---- Login completo del invitado ----
    lg = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": contrasena_temporal})
    vt = await client.post("/auth/login/verify-totp", json={
        "pending_token": lg.json()["pending_token"], "codigo": codigo_totp(secreto_inv, siguiente=True),
    })
    inv_token = vt.json()["access_token"]
    inv_headers = {"Authorization": f"Bearer {inv_token}"}

    # ---- Rutas de negocio bloqueadas hasta cambiar la contraseña (decisión #11) ----
    r = await client.get("/users", headers=inv_headers)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    # ---- Cambia la contraseña (forzado) ----
    r = await client.post("/auth/password/change", headers=inv_headers, json={
        "contrasena_actual": contrasena_temporal, "contrasena_nueva": CONTRASENA_NUEVA,
    })
    assert r.status_code == 200, r.text

    # Tokens viejos mueren tras el cambio
    r = await client.get("/users", headers=inv_headers)
    assert r.status_code == 401

    # Login nuevo con la contraseña cambiada (3ª verificación TOTP: espera ventana nueva,
    # el replay bloquea la 3ª verificación dentro de la misma ventana de 30s)
    from tests.conftest import esperar_ventana_totp
    await esperar_ventana_totp()
    lg = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": CONTRASENA_NUEVA})
    vt = await client.post("/auth/login/verify-totp", json={
        "pending_token": lg.json()["pending_token"], "codigo": codigo_totp(secreto_inv, siguiente=True),
    })
    inv_token2 = vt.json()["access_token"]
    inv_headers2 = {"Authorization": f"Bearer {inv_token2}"}

    # Ahora sí puede listar usuarios (analista)
    r = await client.get("/users", headers=inv_headers2)
    assert r.status_code == 200, r.text
    correos = {u["correo"] for u in r.json()["items"]}
    assert correo_inv in correos

    # El analista NO puede invitar (403) ni cambiar roles (403)
    r = await client.post("/users/invite", headers=inv_headers2, json={"correo": f"x-{_uuid.uuid4().hex[:6]}@scytal.local"})
    assert r.status_code == 403

    # ---- Admin: cambio de rol y desactivación ----
    r = await client.get("/users", headers=admin_headers)
    users = {u["correo"]: u for u in r.json()["items"]}
    inv_id = users[correo_inv]["id_usuarios"]

    r = await client.patch(f"/users/{inv_id}/role", headers=admin_headers, json={"rol": "admin_organizacion"})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "admin_organizacion"

    r = await client.patch(f"/users/{inv_id}/deactivate", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False

    # Tras desactivar, el invitado no puede loguear
    r = await client.post("/auth/login", json={"correo": correo_inv, "contrasena": CONTRASENA_NUEVA})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # Duplicado de invitación → 409
    r = await client.post("/users/invite", headers=admin_headers, json={"correo": correo_admin})
    assert r.status_code == 409
