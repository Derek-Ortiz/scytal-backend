import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard
from tests.integration.test_campaigns import _agregar_destinatario, _crear_campana, _simular, correo_falso
from tests.integration.test_groups import _crear_analista, _crear_grupo, _org_con_token
from tests.integration.test_templates import _crear_plantilla

@pytest.mark.asyncio
async def test_reports_campana_csv_y_pdf(client, integration_guard, correo_falso):
    reg, tok = await _org_con_token(client, "rep")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Comercial")
    p = await _crear_plantilla(client, tok)
    ana = f"ana-{_uuid.uuid4().hex[:6]}@corp.local"
    await _agregar_destinatario(client, tok, g["id_grupos"], ana)
    await _agregar_destinatario(client, tok, g["id_grupos"], f"beto-{_uuid.uuid4().hex[:6]}@corp.local")

    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"])
    cid = c["id_campanas"]
    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json={"canales": ["correo"]})
    assert r.status_code == 200, r.text
    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    await _simular(cid, ana, abrio=True, clico=True, subio=True)
    r = await client.post(f"/campaigns/{cid}/finish", headers=headers)
    assert r.status_code == 200, r.text

    r = await client.get(f"/reports/campaigns/{cid}/export", headers=headers, params={"format": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in r.headers["content-disposition"]
    texto = r.content.decode("utf-8-sig")
    assert "Reporte de campaña" in texto
    assert "Embudo" in texto and "Resultados por destinatario" in texto
    assert ana in texto
    filas = [l for l in texto.splitlines() if l.endswith((",medio", ",alto", ",bajo", ",critico"))]
    assert len(filas) == 2

    r = await client.get(f"/reports/campaigns/{cid}/export", headers=headers, params={"format": "pdf"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert "attachment" in r.headers["content-disposition"]

    r = await client.get(f"/reports/campaigns/{cid}/export", headers=headers, params={"format": "xlsx"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"

    r = await client.get(f"/reports/campaigns/{_uuid.uuid4()}/export", headers=headers, params={"format": "csv"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"

    r = await client.get(f"/reports/campaigns/{cid}/export", params={"format": "csv"})
    assert r.status_code == 401

    r = await client.get("/audit", headers=headers, params={"tipo": "report_exported", "limit": 100})
    assert r.status_code == 200 and r.json()["total"] >= 2

@pytest.mark.asyncio
async def test_reports_grupo_csv_y_pdf(client, integration_guard):
    reg, tok = await _org_con_token(client, "repg")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Soporte")
    r = await client.get(f"/reports/groups/{g['id_grupos']}/export", headers=headers, params={"format": "csv"})
    assert r.status_code == 200, r.text
    texto = r.content.decode("utf-8-sig")
    assert "Reporte de madurez por grupo" in texto and "Soporte" in texto
    assert "Distribución por nivel" in texto

    r = await client.get(f"/reports/groups/{g['id_grupos']}/export", headers=headers, params={"format": "pdf"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"

    r = await client.get(f"/reports/groups/{_uuid.uuid4()}/export", headers=headers, params={"format": "csv"})
    assert r.status_code == 404

    _, tok_an = await _crear_analista(client, reg["org_id"])
    r = await client.get(f"/reports/groups/{g['id_grupos']}/export", headers={"Authorization": f"Bearer {tok_an}"}, params={"format": "csv"})
    assert r.status_code == 200, r.text

    reg_b, tok_b = await _org_con_token(client, "repgb")
    r = await client.get(f"/reports/groups/{g['id_grupos']}/export", headers={"Authorization": f"Bearer {tok_b}"}, params={"format": "csv"})
    assert r.status_code == 404, r.text
