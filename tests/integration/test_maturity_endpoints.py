import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard
from tests.integration.test_campaigns import _agregar_destinatario, _crear_campana, _simular, correo_falso
from tests.integration.test_groups import _crear_grupo, _org_con_token
from tests.integration.test_templates import _crear_plantilla

async def _campana_finalizada(client, tok: str, headers: dict, grupo_id: str, plantilla_id: str, interacciones: dict):
    c = await _crear_campana(client, tok, grupo_id, plantilla_id)
    cid = c["id_campanas"]
    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["correo"]})
    assert r.status_code == 200, r.text
    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    for correo, kwargs in interacciones.items():
        await _simular(cid, correo, **kwargs)
    r = await client.post(f"/campaigns/{cid}/finish", headers=headers)
    assert r.status_code == 200, r.text
    return c

@pytest.mark.asyncio
async def test_maturity_flujo_completo(client, integration_guard, correo_falso):
    reg, tok = await _org_con_token(client, "matur")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Comercial")
    p = await _crear_plantilla(client, tok)
    ana, beto = f"ana-{_uuid.uuid4().hex[:6]}@corp.local", f"beto-{_uuid.uuid4().hex[:6]}@corp.local"
    await _agregar_destinatario(client, tok, g["id_grupos"], ana)
    await _agregar_destinatario(client, tok, g["id_grupos"], beto)

    await _campana_finalizada(client, tok, headers, g["id_grupos"], p["id_plantillas"], {ana: {"abrio": True}})

    r = await client.get(f"/maturity/groups/{g['id_grupos']}/trend", headers=headers)
    assert r.status_code == 200, r.text
    trend = r.json()
    assert trend["grupo_id"] == g["id_grupos"] and len(trend["items"]) == 1
    punto = trend["items"][0]
    assert punto["n_destinatarios"] == 2 and punto["finalizada_en"] is not None
    assert abs(punto["promedio"] - (75 + 100) / 2) < 0.01

    await _campana_finalizada(client, tok, headers, g["id_grupos"], p["id_plantillas"], {beto: {"clico": True, "subio": True}})
    r = await client.get(f"/maturity/groups/{g['id_grupos']}/trend", headers=headers)
    trend2 = r.json()
    assert len(trend2["items"]) == 2
    assert trend2["items"][0]["promedio"] != trend2["items"][1]["promedio"]

    r = await client.get("/recipients", headers=headers, params={"limit": 100})
    assert r.status_code == 200, r.text
    ids = [i["id_destinatarios"] for i in r.json()["items"]]
    assert len(ids) == 2

    rid_ana = next(i["id_destinatarios"] for i in r.json()["items"] if i["correo"] == ana)
    r = await client.get(f"/maturity/recipients/{rid_ana}/history", headers=headers)
    assert r.status_code == 200, r.text
    hist = r.json()
    assert hist["destinatario_id"] == rid_ana and len(hist["items"]) >= 1
    assert all("puntaje_phishing" in i and i["nivel"] in ("bajo", "medio", "alto", "critico") for i in hist["items"])

    r = await client.get("/maturity/organization/summary", headers=headers)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["destinatarios_activos"] == 2
    assert res["indice_promedio"] is not None
    assert sum(res["distribucion"].values()) == 2
    assert res["campanas"]["total"] == 2 and res["campanas"]["completadas"] == 2
    assert res["ultima_finalizacion"] is not None

    r = await client.get("/maturity/organization/summary", headers={"Authorization": f"Bearer {_uuid.uuid4()}"})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_maturity_404_y_aislamiento(client, integration_guard):
    reg, tok = await _org_con_token(client, "matura")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Solos")

    r = await client.get(f"/maturity/groups/{_uuid.uuid4()}/trend", headers=headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = await client.get(f"/maturity/recipients/{_uuid.uuid4()}/history", headers=headers)
    assert r.status_code == 404

    reg_b, tok_b = await _org_con_token(client, "maturb")
    g_b = await _crear_grupo(client, tok_b, "Ajenos")
    r = await client.get(f"/maturity/groups/{g['id_grupos']}/trend", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404, r.text

    r = await client.get("/maturity/organization/summary", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 200
    vacio = r.json()
    assert vacio["indice_promedio"] is None and vacio["campanas"]["total"] == 0
    assert sum(vacio["distribucion"].values()) == 0

    r = await client.get("/maturity/organization/summary")
    assert r.status_code == 401
