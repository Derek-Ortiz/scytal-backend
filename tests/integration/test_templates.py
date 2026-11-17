"""Pruebas de integración /templates (§4.7): CRUD, leyenda obligatoria, delete-en-uso 409,
plantillas globales de solo lectura, permisos de analista y aislamiento multi-tenant.

Requiere docker compose corriendo (db + redis en 127.0.0.1). Se salta si no hay BD.
"""
import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.integration.test_groups import _crear_grupo, _crear_analista, _org_con_token  # noqa: E402
from tests.integration.test_multitenant import CONTRASENA_A  # noqa: E402


async def _crear_plantilla(client, tok: str, nombre: str = "Login falso", **extra) -> dict:
    datos = {
        "nombre": nombre, "perfil": "corporativo", "canal": "correo", "asunto": "Verifica tu cuenta",
        "contenido_html": "<p>Entra aquí {{enlace}}</p>", "landing_html": "<html><body>Formulario</body></html>",
    }
    datos.update(extra)
    r = await client.post("/templates", headers={"Authorization": f"Bearer {tok}"}, json=datos)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_plantillas_flujo_completo(client, integration_guard, monkeypatch):
    reg_a, tok_a = await _org_con_token(client, "plant")
    headers = {"Authorization": f"Bearer {tok_a}"}

    # Crear: la leyenda "PÁGINA DE PRUEBA" se añade sola a la landing
    p = await _crear_plantilla(client, tok_a)
    assert "PÁGINA DE PRUEBA" in p["landing_html"]
    assert p["org_id"] == reg_a["org_id"] and p["en_uso"] is False

    # canal=correo sin asunto → 422 (§5, validado en schema)
    r = await client.post("/templates", headers=headers, json={
        "nombre": "Sin asunto", "perfil": "corporativo", "canal": "correo",
        "contenido_html": "<p>x</p>", "landing_html": "<html></html>",
    })
    assert r.status_code == 422, r.text
    # canal=qr SÍ puede ir sin asunto, y canal inválido → 422
    p_qr = await _crear_plantilla(client, tok_a, "QR lobby", canal="qr", asunto=None)
    assert p_qr["asunto"] is None and p_qr["canal"] == "qr"
    r = await client.post("/templates", headers=headers, json={
        "nombre": "SMS", "perfil": "x", "canal": "sms", "contenido_html": "x", "landing_html": "x",
    })
    assert r.status_code == 422

    # Listado con filtros (la BD puede contener residuos de corridas previas: se aserta por nombre)
    r = await client.get("/templates", headers=headers)
    assert r.status_code == 200
    nombres = [i["nombre"] for i in r.json()["items"]]
    assert "Login falso" in nombres and "QR lobby" in nombres
    r = await client.get("/templates", headers=headers, params={"canal": "qr"})
    assert r.status_code == 200 and [i["nombre"] for i in r.json()["items"]] == ["QR lobby"]
    r = await client.get("/templates", headers=headers, params={"perfil": "no-existe"})
    assert r.status_code == 200 and r.json()["total"] == 0

    # Detalle + PATCH parcial (regla final canal⇒asunto con el valor guardado)
    r = await client.get(f"/templates/{p['id_plantillas']}", headers=headers)
    assert r.status_code == 200 and r.json()["contenido_html"].startswith("<p>")
    r = await client.patch(f"/templates/{p['id_plantillas']}", headers=headers, json={"nombre": "Login v2"})
    assert r.status_code == 200 and r.json()["nombre"] == "Login v2"
    # la plantilla es correo con asunto guardado → cambiar a qr está OK; a qr y luego de vuelta...
    r = await client.patch(f"/templates/{p['id_plantillas']}", headers=headers, json={"canal": "qr"})
    assert r.status_code == 200 and r.json()["canal"] == "qr"
    # PATCH solo-espacios → 422
    r = await client.patch(f"/templates/{p['id_plantillas']}", headers=headers, json={"nombre": "   "})
    assert r.status_code == 422
    # PATCH vacío → 422
    r = await client.patch(f"/templates/{p['id_plantillas']}", headers=headers, json={})
    assert r.status_code == 422
    # qr SIN asunto guardado → volver a correo sin asunto explícito → 422 (§5)
    r = await client.patch(f"/templates/{p_qr['id_plantillas']}", headers=headers, json={"canal": "correo"})
    assert r.status_code == 422, r.text
    # con asunto explícito sí (p ya trae asunto guardado; aquí se fija uno nuevo)
    r = await client.patch(
        f"/templates/{p['id_plantillas']}", headers=headers, json={"canal": "correo", "asunto": "Nuevo asunto"}
    )
    assert r.status_code == 200 and r.json()["asunto"] == "Nuevo asunto"

    # Analista: lee, no escribe
    _, tok_analista = await _crear_analista(client, reg_a["org_id"])
    h_a = {"Authorization": f"Bearer {tok_analista}"}
    r = await client.get("/templates", headers=h_a)
    assert r.status_code == 200
    nombres_a = [i["nombre"] for i in r.json()["items"]]
    assert "Login v2" in nombres_a and "QR lobby" in nombres_a
    r = await client.post("/templates", headers=h_a, json={
        "nombre": "H", "perfil": "x", "canal": "qr", "contenido_html": "x", "landing_html": "x",
    })
    assert r.status_code == 403
    r = await client.delete(f"/templates/{p['id_plantillas']}", headers=h_a)
    assert r.status_code == 403

    # Multi-tenant: otra org no ve las plantillas DE LA ORG A (las globales sí, §6.1)
    _, tok_b = await _org_con_token(client, "plantb")
    h_b = {"Authorization": f"Bearer {tok_b}"}
    r = await client.get("/templates", headers=h_b)
    assert r.status_code == 200
    nombres_b = [i["nombre"] for i in r.json()["items"]]
    assert "Login v2" not in nombres_b and "QR lobby" not in nombres_b
    r = await client.get(f"/templates/{p['id_plantillas']}", headers=h_b)
    assert r.status_code == 404
    r = await client.patch(f"/templates/{p['id_plantillas']}", headers=h_b, json={"nombre": "hack"})
    assert r.status_code == 404

    # Sin token → 401
    r = await client.get("/templates")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_plantilla_global_solo_lectura(client, integration_guard):
    """org_id NULL = global: la lee cualquier org, nadie la edita ni la borra (403)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.plantilla import Plantilla

    NOMBRE = "Global de plataforma"
    async with SessionLocal() as db:
        existe = (await db.execute(
            select(Plantilla).where(Plantilla.org_id.is_(None), Plantilla.nombre == NOMBRE)
        )).scalar_one_or_none()
        if existe is None:  # idempotente: las corridas previas la dejaron en la BD
            db.add(Plantilla(
                org_id=None, nombre=NOMBRE, perfil="corporativo", canal="correo",
                asunto="Aviso global", contenido_html="<p>global {{enlace}}</p>",
                landing_html="<html>global</html>",
            ))
            await db.commit()

    reg_a, tok_a = await _org_con_token(client, "gplant")
    headers = {"Authorization": f"Bearer {tok_a}"}
    r = await client.get("/templates", headers=headers)
    items = r.json()["items"]
    global_item = next(i for i in items if i["nombre"] == "Global de plataforma")
    global_id = global_item["id_plantillas"]
    assert global_item["org_id"] is None

    r = await client.get(f"/templates/{global_id}", headers=headers)
    assert r.status_code == 200
    r = await client.patch(f"/templates/{global_id}", headers=headers, json={"nombre": "hack"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = await client.delete(f"/templates/{global_id}", headers=headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_plantilla_delete_bloqueado_por_campana_activa(client, integration_guard):
    """DELETE → 409 si una campaña pendiente/activa la usa; cancelada la suelta (204)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.campana import Campana

    reg_a, tok_a = await _org_con_token(client, "delplant")
    headers = {"Authorization": f"Bearer {tok_a}"}
    g = await _crear_grupo(client, tok_a, "Soporte")
    p = await _crear_plantilla(client, tok_a, "Para borrar")

    r = await client.post("/campaigns", headers=headers, json={
        "nombre": "Campaña con plantilla", "grupo_id": g["id_grupos"], "plantilla_id": p["id_plantillas"],
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id_campanas"]

    r = await client.delete(f"/templates/{p['id_plantillas']}", headers=headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT", r.text

    # con la campaña cancelada sí se puede borrar (campañas viejas → SET NULL)
    r = await client.post(f"/campaigns/{cid}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    r = await client.delete(f"/templates/{p['id_plantillas']}", headers=headers)
    assert r.status_code == 204, r.text

    async with SessionLocal() as db:
        c = (await db.execute(select(Campana).where(Campana.id_campanas == _uuid.UUID(cid)))).scalar_one()
        assert c.plantilla_id is None  # FK ON DELETE SET NULL
