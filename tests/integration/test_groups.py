import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.integration.test_multitenant import (
    CONTRASENA_A, _activar_2fa, _login_provisional, _registrar_org, _tokens_completos,
)

CONTRASENA_ANALISTA = "Relampago-Verde-61-Sigma-8!"

async def _org_con_token(client, prefijo: str) -> tuple[dict, str]:
    """Registra una org nueva con admin activo. Retorna (datos_register, access_token)."""
    correo = f"{prefijo}-{_uuid.uuid4().hex[:8]}@scytal.local"
    reg = await _registrar_org(client, correo, f"Org {prefijo} {_uuid.uuid4().hex[:6]}", None, CONTRASENA_A)
    tok = await _tokens_completos(
        client, correo, CONTRASENA_A,
        await _activar_2fa(client, await _login_provisional(client, correo, CONTRASENA_A)),
    )
    return reg, tok

async def _crear_grupo(client, tok: str, nombre: str, perfil: str = "oficina") -> dict:
    r = await client.post("/groups", headers={"Authorization": f"Bearer {tok}"}, json={"nombre": nombre, "perfil": perfil})
    assert r.status_code == 201, r.text
    return r.json()

async def _crear_analista(client, org_id: str) -> tuple[str, str]:
    """Crea un analista directo en BD (sin pasar por invite) y devuelve (correo, access_token)."""
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario

    correo = f"analista-{_uuid.uuid4().hex[:8]}@scytal.local"
    async with SessionLocal() as db:
        db.add(Usuario(
            org_id=_uuid.UUID(org_id), correo=correo, rol="analista",
            hash_contrasena=hash_password(CONTRASENA_ANALISTA), estado="pendiente_2fa",
            activo=True, debe_cambiar_contrasena=False,
        ))
        await db.commit()
    tok = await _tokens_completos(
        client, correo, CONTRASENA_ANALISTA,
        await _activar_2fa(client, await _login_provisional(client, correo, CONTRASENA_ANALISTA)),
    )
    return correo, tok

@pytest.mark.asyncio
async def test_grupos_flujo_completo(client, integration_guard, monkeypatch):
    """Crear, duplicado 409, listar con métricas, detalle, editar y permisos del analista."""
    reg_a, tok_a = await _org_con_token(client, "grupos")
    headers = {"Authorization": f"Bearer {tok_a}"}

    g = await _crear_grupo(client, tok_a, "Ventas", "comercial")
    assert g["nombre"] == "Ventas" and g["perfil"] == "comercial"
    assert g["metricas"]["destinatarios_activos"] == 0
    assert g["metricas"]["indice_promedio"] is None

    r = await client.post("/groups", headers=headers, json={"nombre": "Ventas", "perfil": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE"
    r = await client.post("/groups", headers=headers, json={"nombre": "  ventas ", "perfil": "x"})
    assert r.status_code == 409, r.text

    r = await client.post("/groups", headers=headers, json={"nombre": "   ", "perfil": "x"})
    assert r.status_code == 422

    r = await client.get("/groups", headers=headers)
    assert r.status_code == 200, r.text
    lista = r.json()
    assert lista["total"] == 1
    assert lista["items"][0]["metricas"]["destinatarios_activos"] == 0

    r = await client.get(f"/groups/{g['id_grupos']}", headers=headers)
    assert r.status_code == 200 and r.json()["nombre"] == "Ventas"

    r = await client.patch(f"/groups/{g['id_grupos']}", headers=headers, json={"nombre": "Ventas Norte"})
    assert r.status_code == 200 and r.json()["nombre"] == "Ventas Norte"
    await _crear_grupo(client, tok_a, "Marketing")
    r = await client.patch(f"/groups/{g['id_grupos']}", headers=headers, json={"nombre": "Marketing"})
    assert r.status_code == 409

    _, tok_analista = await _crear_analista(client, reg_a["org_id"])
    h_analista = {"Authorization": f"Bearer {tok_analista}"}
    r = await client.get("/groups", headers=h_analista)
    assert r.status_code == 200 and r.json()["total"] == 2
    r = await client.post("/groups", headers=h_analista, json={"nombre": "Hacked", "perfil": "x"})
    assert r.status_code == 403
    r = await client.delete(f"/groups/{g['id_grupos']}", headers=h_analista)
    assert r.status_code == 403

    r = await client.get("/groups")
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_grupo_delete_bloqueado_por_campanas_y_cascada(client, integration_guard):
    """DELETE → 409 si hay campañas (RESTRICT); sin campañas → 204 y los destinatarios se borran en cascada."""
    from app.db.session import SessionLocal
    from app.models.campana import Campana
    from app.models.destinatario import Destinatario
    from sqlalchemy import select

    reg_a, tok_a = await _org_con_token(client, "delgrp")
    org_id = _uuid.UUID(reg_a["org_id"])
    headers = {"Authorization": f"Bearer {tok_a}"}
    g = await _crear_grupo(client, tok_a, "Con Campana")
    gid = _uuid.UUID(g["id_grupos"])

    async with SessionLocal() as db:
        db.add(Campana(org_id=org_id, grupo_id=gid, nombre="Camp 1", estado="pendiente"))
        await db.commit()

    r = await client.delete(f"/groups/{g['id_grupos']}", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "CONFLICT"

    async with SessionLocal() as db:
        camp = (await db.execute(select(Campana).where(Campana.grupo_id == gid))).scalar_one()
        await db.delete(camp)
        db.add(Destinatario(org_id=org_id, grupo_id=gid, correo="cascada@x.com"))
        await db.commit()
    r = await client.delete(f"/groups/{g['id_grupos']}", headers=headers)
    assert r.status_code == 204, r.text
    r = await client.get(f"/groups/{g['id_grupos']}", headers=headers)
    assert r.status_code == 404
    async with SessionLocal() as db:
        quedan = (await db.execute(select(Destinatario).where(Destinatario.grupo_id == gid))).scalars().all()
    assert quedan == []

@pytest.mark.asyncio
async def test_aislamiento_multi_tenant_grupos(client, integration_guard):
    """La org B no puede leer/editar/borrar grupos de la org A aunque conozca el UUID (404, no 403)."""
    _, tok_a = await _org_con_token(client, "isoA")
    reg_b, tok_b = await _org_con_token(client, "isoB")
    g = await _crear_grupo(client, tok_a, "Secreto A")
    h_b = {"Authorization": f"Bearer {tok_b}"}

    r = await client.get(f"/groups/{g['id_grupos']}", headers=h_b)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = await client.patch(f"/groups/{g['id_grupos']}", headers=h_b, json={"nombre": "Hackeado"})
    assert r.status_code == 404
    r = await client.delete(f"/groups/{g['id_grupos']}", headers=h_b)
    assert r.status_code == 404

    r = await client.get("/groups", headers=h_b)
    nombres = {i["nombre"] for i in r.json()["items"]}
    assert "Secreto A" not in nombres
