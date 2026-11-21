import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard
from tests.integration.test_campaigns import _agregar_destinatario, _crear_campana, _simular, correo_falso
from tests.integration.test_groups import _crear_analista, _crear_grupo, _org_con_token
from tests.integration.test_templates import _crear_plantilla

async def _campana_finalizada_con_alerta(client, tok: str, headers: dict) -> tuple[dict, dict]:
    g = await _crear_grupo(client, tok, f"Alertas {_uuid.uuid4().hex[:6]}")
    p = await _crear_plantilla(client, tok)
    sufijo = _uuid.uuid4().hex[:6]
    victima = f"victima-{sufijo}@corp.local"
    await _agregar_destinatario(client, tok, g["id_grupos"], victima)
    await _agregar_destinatario(client, tok, g["id_grupos"], f"resistente-{sufijo}@corp.local")
    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"])
    cid = c["id_campanas"]
    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["correo"]})
    assert r.status_code == 200, r.text
    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    await _simular(cid, victima, abrio=True, clico=True, subio=True)
    r = await client.post(f"/campaigns/{cid}/finish", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["alertas"] == 1
    return c, g

@pytest.mark.asyncio
async def test_alerts_flujo_completo(client, integration_guard, correo_falso):
    reg, tok = await _org_con_token(client, "alert")
    headers = {"Authorization": f"Bearer {tok}"}

    await _campana_finalizada_con_alerta(client, tok, headers)

    r = await client.get("/alerts", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    a = data["items"][0]
    assert a["tipo"] == "riesgo_phishing" and a["resuelto"] is False and a["resuelto_en"] is None
    assert a["referencia_tipo"] == "destinatario" and a["referencia_id"] is not None

    r = await client.get("/alerts", headers=headers, params={"resuelto": "false"})
    assert r.json()["total"] == 1
    r = await client.get("/alerts", headers=headers, params={"resuelto": "true"})
    assert r.json()["total"] == 0
    r = await client.get("/alerts", headers=headers, params={"tipo": "otra_cosa"})
    assert r.json()["total"] == 0
    r = await client.get("/alerts", headers=headers, params={"tipo": "riesgo_phishing"})
    assert r.json()["total"] == 1

    r = await client.patch(f"/alerts/{a['id_alertas']}/resolve", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["resuelto"] is True and r.json()["resuelto_en"] is not None

    r = await client.patch(f"/alerts/{a['id_alertas']}/resolve", headers=headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT"

    r = await client.get("/alerts", headers=headers, params={"resuelto": "true"})
    assert r.json()["total"] == 1
    r = await client.get("/alerts", headers=headers, params={"resuelto": "false"})
    assert r.json()["total"] == 0

    r = await client.get("/audit", headers=headers, params={"tipo": "alert_resolved", "limit": 100})
    assert r.status_code == 200 and r.json()["total"] >= 1

    r = await client.patch(f"/alerts/{_uuid.uuid4()}/resolve", headers=headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"

    r = await client.get("/alerts")
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_alerts_permisos_y_aislamiento(client, integration_guard, correo_falso):
    reg, tok = await _org_con_token(client, "alertp")
    headers = {"Authorization": f"Bearer {tok}"}
    await _campana_finalizada_con_alerta(client, tok, headers)

    r = await client.get("/alerts", headers=headers)
    alerta_id = r.json()["items"][0]["id_alertas"]

    _, tok_an = await _crear_analista(client, reg["org_id"])
    r = await client.get("/alerts", headers={"Authorization": f"Bearer {tok_an}"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1

    r = await client.patch(f"/alerts/{alerta_id}/resolve", headers={"Authorization": f"Bearer {tok_an}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"

    reg_b, tok_b = await _org_con_token(client, "alertb")
    r = await client.get("/alerts", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 200 and r.json()["total"] == 0

    r = await client.patch(f"/alerts/{alerta_id}/resolve", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404, r.text
