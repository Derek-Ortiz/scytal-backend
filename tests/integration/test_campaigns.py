import re
import uuid as _uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.integration

from app.services import campana_service
from tests.integration.test_groups import _crear_analista, _crear_grupo, _org_con_token
from tests.integration.test_templates import _crear_plantilla

@pytest.fixture
def correo_falso(monkeypatch):
    """Reemplaza el envío SMTP: captura los lotes y devuelve éxito individual."""
    enviados: list[list[tuple]] = []

    async def _falso(lote, *, request_id=None):
        enviados.append(list(lote))
        return [True] * len(lote)

    monkeypatch.setattr(campana_service, "_enviar_lote", _falso)
    return enviados

async def _agregar_destinatario(client, tok: str, grupo_id: str, correo: str) -> dict:
    r = await client.post(
        "/recipients", headers={"Authorization": f"Bearer {tok}"}, json={"correo": correo, "grupo_id": grupo_id}
    )
    assert r.status_code == 201, r.text
    return r.json()

async def _crear_campana(client, tok: str, grupo_id: str, plantilla_id: str | None = None, **extra) -> dict:
    datos = {"nombre": f"Campaña {_uuid.uuid4().hex[:6]}", "grupo_id": grupo_id, "expiracion_horas": 24}
    if plantilla_id:
        datos["plantilla_id"] = plantilla_id
    datos.update(extra)
    r = await client.post("/campaigns", headers={"Authorization": f"Bearer {tok}"}, json=datos)
    assert r.status_code == 201, r.text
    return r.json()

async def _fila_token(campana_id: str, correo: str):
    from app.db.session import SessionLocal
    from app.models.campana import DestinatarioCampana
    from app.models.destinatario import Destinatario

    async with SessionLocal() as db:
        res = await db.execute(
            select(DestinatarioCampana)
            .join(Destinatario, Destinatario.id_destinatarios == DestinatarioCampana.destinatario_id)
            .where(DestinatarioCampana.campana_id == _uuid.UUID(campana_id), Destinatario.correo == correo)
        )
        return res.scalar_one()

async def _simular(campana_id: str, correo: str, *, abrio=False, clico=False, subio=False):
    """Escrituras directas: mismas columnas/eventos que escribirá /track en Fase 4."""
    from app.db.session import SessionLocal
    from app.models.campana import DestinatarioCampana
    from app.models.tracking import EventoTracking

    fila = await _fila_token(campana_id, correo)
    ahora = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        valores = {}
        if abrio:
            valores["abierto_en"] = ahora
        if clico:
            valores["clic_en"] = ahora
        if valores:
            await db.execute(
                update(DestinatarioCampana)
                .where(DestinatarioCampana.id_destinatarios_campana == fila.id_destinatarios_campana)
                .values(**valores)
            )
        if subio:
            db.add(EventoTracking(
                destinatario_campana_id=fila.id_destinatarios_campana, tipo="subido", canal_origen="correo"
            ))
        await db.commit()

def _tokens_de(correo_falso_lotes) -> list[str]:
    toks = []
    for lote in correo_falso_lotes:
        for item in lote:
            m = re.search(r"track/click\?t=([0-9a-f]{64})", item[3] or "")
            if m:
                toks.append(m.group(1))
    return toks

@pytest.mark.asyncio
async def test_campana_flujo_completo(client, integration_guard, correo_falso):
    reg, tok = await _org_con_token(client, "camp")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Oficina Central")
    p = await _crear_plantilla(client, tok)
    d1 = await _agregar_destinatario(client, tok, g["id_grupos"], "ana@corp.local")
    d2 = await _agregar_destinatario(client, tok, g["id_grupos"], "beto@corp.local")
    d3 = await _agregar_destinatario(client, tok, g["id_grupos"], "carla@corp.local")

    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"], expiracion_horas=24)
    cid = c["id_campanas"]
    assert c["estado"] == "pendiente" and c["expiracion_horas"] == 24 and c["canales"] == []

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 422, r.text
    c2 = await _crear_campana(client, tok, g["id_grupos"], plantilla_id=None)
    r = await client.post(f"/campaigns/{c2['id_campanas']}/launch", headers=headers)
    assert r.status_code == 422, r.text

    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["correo"]})
    assert r.status_code == 200 and r.json()["canales"] == [{"canal": "correo", "zonas": []}]

    r = await client.patch(f"/campaigns/{cid}", headers=headers, json={"nombre": "Fase Q4", "expiracion_horas": 48})
    assert r.status_code == 200 and r.json()["nombre"] == "Fase Q4" and r.json()["expiracion_horas"] == 48

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campana"]["estado"] == "activa" and body["emails_programados"] == 3
    assert body["campana"]["iniciada_en"] is not None
    assert len(correo_falso) == 1
    tokens = _tokens_de(correo_falso)
    assert len(tokens) == 3 and len(set(tokens)) == 3

    r = await client.get(f"/campaigns/{cid}/recipients", headers=headers)
    filas = {f["correo"]: f for f in r.json()["items"]}
    assert all(filas[k]["enviado"] for k in filas) and all(filas[k]["vencido"] is False for k in filas)
    assert all(filas[k]["abrio"] is False for k in filas)

    r = await client.get(f"/campaigns/{cid}/stats", headers=headers)
    s = r.json()
    assert (s["total_destinatarios"], s["enviados"], s["abiertos"], s["clics"], s["subidos"], s["qr_clics"]) == (3, 3, 0, 0, 0, 0)

    r = await client.patch(f"/campaigns/{cid}", headers=headers, json={"nombre": "hack"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT"
    r = await client.patch(f"/campaigns/{cid}", headers=headers, json={})
    assert r.status_code == 422
    r = await client.patch(f"/campaigns/{cid}", headers=headers, json={"expiracion_horas": 0})
    assert r.status_code == 422
    r = await client.patch(f"/campaigns/{cid}", headers=headers, json={"expiracion_horas": 96})
    assert r.status_code == 200 and r.json()["expiracion_horas"] == 96

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 409

    await _simular(cid, "ana@corp.local", abrio=True)
    await _simular(cid, "beto@corp.local", clico=True, subio=True)
    r = await client.get(f"/campaigns/{cid}/stats", headers=headers)
    s = r.json()
    assert (s["abiertos"], s["clics"], s["subidos"]) == (1, 1, 1)

    r = await client.post(f"/campaigns/{cid}/finish", headers=headers)
    assert r.status_code == 200, r.text
    fin = r.json()
    assert fin["campana"]["estado"] == "completada" and fin["campana"]["finalizada_en"] is not None
    assert fin["instantaneas"] == 3 and fin["alertas"] == 1

    r = await client.get(f"/campaigns/{cid}/recipients", headers=headers)
    filas = {f["correo"]: f for f in r.json()["items"]}
    assert filas["ana@corp.local"]["puntaje_phishing"] == 75.0 and filas["ana@corp.local"]["nivel"] == "medio"
    assert filas["beto@corp.local"]["puntaje_phishing"] == 25.0 and filas["beto@corp.local"]["nivel"] == "critico"
    assert filas["carla@corp.local"]["puntaje_phishing"] == 100.0 and filas["carla@corp.local"]["nivel"] == "alto"

    r = await client.get(f"/groups/{g['id_grupos']}", headers=headers)
    prom = r.json()["metricas"]["indice_promedio"]
    assert prom is not None and abs(prom - (75 + 25 + 100) / 3) < 0.01

    r = await client.post(f"/campaigns/{cid}/finish", headers=headers)
    assert r.status_code == 409

    r = await client.post(f"/campaigns/{cid}/send-feedback", headers=headers)
    assert r.status_code == 200 and r.json()["emails_programados"] == 3
    assert len(correo_falso[-1]) == 3 and "índice de resistencia" in correo_falso[-1][0][2]
    r = await client.get(f"/campaigns/{cid}", headers=headers)
    assert r.json()["feedback_enviado_en"] is not None
    r = await client.post(f"/campaigns/{cid}/send-feedback", headers=headers)
    assert r.status_code == 409

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["campana"]["estado"] == "activa"
    r = await client.get(f"/campaigns/{cid}/stats", headers=headers)
    s = r.json()
    assert (s["enviados"], s["abiertos"], s["clics"], s["subidos"]) == (3, 0, 0, 0)
    r = await client.get(f"/campaigns/{cid}/recipients", headers=headers)
    filas = {f["correo"]: f for f in r.json()["items"]}
    assert filas["ana@corp.local"]["abrio"] is False
    assert filas["ana@corp.local"]["puntaje_phishing"] == 75.0

    r = await client.post(f"/campaigns/{cid}/send-feedback", headers=headers)
    assert r.status_code == 409
    r = await client.post(f"/campaigns/{cid}/finish", headers=headers)
    assert r.status_code == 200 and r.json()["instantaneas"] == 3 and r.json()["alertas"] == 0

@pytest.mark.asyncio
async def test_campana_qr_zonas_cancel_y_relanzamiento(client, integration_guard, correo_falso):
    reg, tok = await _org_con_token(client, "qr")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Planta")
    await _agregar_destinatario(client, tok, g["id_grupos"], "obrero1@planta.local")
    await _agregar_destinatario(client, tok, g["id_grupos"], "obrero2@planta.local")
    p = await _crear_plantilla(client, tok, "QR form", canal="qr", asunto=None)
    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"])
    cid = c["id_campanas"]

    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["qr"]})
    assert r.status_code == 422, r.text
    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["correo"], "zonas": ["Recepción"]})
    assert r.status_code == 422

    r = await client.post(
        f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["qr", "correo"], "zonas": ["Recepción", "Comedor"]}
    )
    assert r.status_code == 200
    assert r.json()["canales"] == [
        {"canal": "correo", "zonas": []}, {"canal": "qr", "zonas": ["Recepción", "Comedor"]},
    ]

    r = await client.get(f"/campaigns/{cid}/qr", headers=headers)
    assert r.status_code == 200, r.text
    zonas = r.json()["zonas"]
    assert [z["zona"] for z in zonas] == ["Recepción", "Comedor"]
    assert all(z["url"].startswith("http") and "/track/click?t=" in z["url"] for z in zonas)
    assert all(z["qr_base64"].startswith("iVBOR") for z in zonas)

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200 and r.json()["emails_programados"] == 2 and r.json()["zonas_qr"] == 2

    r = await client.post(f"/campaigns/{cid}/cancel", headers=headers)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    for correo in ("obrero1@planta.local", "obrero2@planta.local"):
        from app.db.session import SessionLocal
        from app.models.campana import DestinatarioCampana

        fila = await _fila_token(cid, correo)
        async with SessionLocal() as db:
            f = (await db.execute(
                select(DestinatarioCampana).where(DestinatarioCampana.id_destinatarios_campana == fila.id_destinatarios_campana)
            )).scalar_one()
            assert f.expira_en <= datetime.now(timezone.utc)
            assert f.expira_en.tzinfo is not None

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers, json={"expiracion_horas": 12})
    assert r.status_code == 200, r.text
    assert r.json()["campana"]["estado"] == "activa"
    fila = await _fila_token(cid, "obrero1@planta.local")
    from app.db.session import SessionLocal
    from app.models.campana import DestinatarioCampana

    async with SessionLocal() as db:
        f = (await db.execute(
            select(DestinatarioCampana).where(DestinatarioCampana.id_destinatarios_campana == fila.id_destinatarios_campana)
        )).scalar_one()
        assert f.expira_en > datetime.now(timezone.utc)

    r = await client.post(f"/campaigns/{cid}/cancel", headers=headers)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    c2 = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"])
    r = await client.post(f"/campaigns/{c2['id_campanas']}/cancel", headers=headers)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    r = await client.post(f"/campaigns/{c2['id_campanas']}/cancel", headers=headers)
    assert r.status_code == 409

    from app.models.qr_zona import CampanaQrZona

    async with SessionLocal() as db:
        zona = (await db.execute(select(CampanaQrZona).where(CampanaQrZona.campana_id == _uuid.UUID(cid)))).scalars().first()
        await db.execute(
            update(CampanaQrZona).where(CampanaQrZona.id_campanas_qr_zonas == zona.id_campanas_qr_zonas)
            .values(clic_en=datetime.now(timezone.utc))
        )
        await db.commit()
    r = await client.get(f"/campaigns/{cid}/stats", headers=headers)
    s = r.json()
    assert s["qr_clics"] == 1 and s["abiertos"] == 0 and s["clics"] == 0

@pytest.mark.asyncio
async def test_campana_permisos_y_multitenant(client, integration_guard):
    reg_a, tok_a = await _org_con_token(client, "campa")
    headers_a = {"Authorization": f"Bearer {tok_a}"}
    g = await _crear_grupo(client, tok_a, "Ventas")
    c = await _crear_campana(client, tok_a, g["id_grupos"])

    _, tok_analista = await _crear_analista(client, reg_a["org_id"])
    h_a = {"Authorization": f"Bearer {tok_analista}"}
    r = await client.get(f"/campaigns/{c['id_campanas']}", headers=h_a)
    assert r.status_code == 200
    r = await client.get(f"/campaigns/{c['id_campanas']}/stats", headers=h_a)
    assert r.status_code == 200
    for metodo, path, json_body in (
        ("patch", f"/campaigns/{c['id_campanas']}", {"nombre": "x"}),
        ("post", f"/campaigns/{c['id_campanas']}/channels", {"canales": ["correo"]}),
        ("post", f"/campaigns/{c['id_campanas']}/launch", None),
        ("post", f"/campaigns/{c['id_campanas']}/cancel", None),
    ):
        r = await getattr(client, metodo)(path, headers=h_a, json=json_body)
        assert r.status_code == 403, f"{metodo} {path}"

    _, tok_b = await _org_con_token(client, "campb")
    h_b = {"Authorization": f"Bearer {tok_b}"}
    r = await client.get("/campaigns", headers=h_b)
    assert r.status_code == 200 and r.json()["total"] == 0
    for path in (
        f"/campaigns/{c['id_campanas']}", f"/campaigns/{c['id_campanas']}/stats",
        f"/campaigns/{c['id_campanas']}/recipients", f"/campaigns/{c['id_campanas']}/qr",
    ):
        r = await client.get(path, headers=h_b)
        assert r.status_code == 404, path

    r = await client.get("/campaigns", headers=headers_a, params={"estado": "pendiente"})
    assert r.status_code == 200 and r.json()["total"] == 1
    r = await client.get("/campaigns", headers=headers_a, params={"estado": "activa"})
    assert r.json()["total"] == 0
    r = await client.get("/campaigns", headers=headers_a, params={"estado": "no-existe"})
    assert r.status_code == 422
    r = await client.get("/campaigns", headers=headers_a, params={"grupo_id": g["id_grupos"]})
    assert r.json()["total"] == 1

@pytest.mark.asyncio
async def test_campana_launch_exige_destinatarios_activos(client, integration_guard, correo_falso):
    """Launch sin destinatarios activos en el grupo → 422; con uno desactivado tampoco cuenta."""
    reg, tok = await _org_con_token(client, "campd")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Vacío")
    p = await _crear_plantilla(client, tok)
    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"])
    await client.post(f"/campaigns/{c['id_campanas']}/channels", headers=headers, json={"canales": ["correo"]})
    r = await client.post(f"/campaigns/{c['id_campanas']}/launch", headers=headers)
    assert r.status_code == 422, r.text
    assert "destinatarios activos" in r.json()["error"]["message"]

    d = await _agregar_destinatario(client, tok, g["id_grupos"], "solito@x.local")
    r = await client.patch(f"/recipients/{d['id_destinatarios']}/deactivate", headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/campaigns/{c['id_campanas']}/launch", headers=headers)
    assert r.status_code == 422
