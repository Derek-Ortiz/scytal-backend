import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard
from tests.integration.test_groups import _org_con_token

@pytest.mark.asyncio
async def test_audit_flujo_y_filtros(client, integration_guard):
    reg, tok = await _org_con_token(client, "audit")
    headers = {"Authorization": f"Bearer {tok}"}

    r = await client.get("/audit", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    tipos = {i["tipo"] for i in data["items"]}
    assert "register" in tipos
    assert all(i["actor_correo"] is None or "@" in i["actor_correo"] for i in data["items"])
    assert all("creado_en" in i and "detalle" in i for i in data["items"])

    r = await client.get("/audit", headers=headers, params={"tipo": "register"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all(i["tipo"] == "register" for i in r.json()["items"])

    r = await client.get("/audit", headers=headers, params={"tipo": "tipo_inexistente"})
    assert r.status_code == 200 and r.json()["total"] == 0

    r = await client.get("/audit", headers=headers, params={"limit": 1, "offset": 0})
    assert r.status_code == 200 and len(r.json()["items"]) == 1 and r.json()["limit"] == 1

    r = await client.get("/audit", headers=headers, params={"limit": 500})
    assert r.status_code == 422

    actor_id = next((i["actor_id"] for i in data["items"] if i["actor_id"]), None)
    if actor_id:
        r = await client.get("/audit", headers=headers, params={"actor_id": actor_id})
        assert r.status_code == 200
        assert all(i["actor_id"] == actor_id for i in r.json()["items"])

    r = await client.get("/audit", headers=headers, params={"desde": "2000-01-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["total"] >= 1
    r = await client.get("/audit", headers=headers, params={"desde": "2999-01-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["total"] == 0

    r = await client.get("/audit")
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_audit_aislamiento_multi_tenant(client, integration_guard):
    reg_a, tok_a = await _org_con_token(client, "audita")
    reg_b, tok_b = await _org_con_token(client, "auditb")

    r = await client.get("/audit", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 200, r.text
    correos = {i["actor_correo"] for i in r.json()["items"] if i["actor_correo"]}
    assert reg_a["correo"] not in correos
    assert reg_b["correo"] in correos

    r = await client.get("/audit", headers={"Authorization": f"Bearer {tok_b}"}, params={"tipo": "register"})
    assert r.json()["total"] >= 1
    assert all(reg_a["correo"] not in (i["detalle"] or "") for i in r.json()["items"])
