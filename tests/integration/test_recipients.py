import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration

from tests.integration.test_groups import _crear_grupo, _crear_analista, _org_con_token

@pytest.mark.asyncio
async def test_destinatarios_flujo_completo(client, integration_guard):
    """Alta, duplicado 409, listado con filtro, histórico, edición, desactivación y métricas del grupo."""
    reg_a, tok_a = await _org_con_token(client, "dest")
    org_id = _uuid.UUID(reg_a["org_id"])
    headers = {"Authorization": f"Bearer {tok_a}"}

    g1 = await _crear_grupo(client, tok_a, "Soporte")
    g2 = await _crear_grupo(client, tok_a, "Finanzas")
    gid1, gid2 = _uuid.UUID(g1["id_grupos"]), _uuid.UUID(g2["id_grupos"])

    r = await client.post("/recipients", headers=headers, json={"correo": "Ana.Lopez@Empresa.com", "grupo_id": str(gid1)})
    assert r.status_code == 201, r.text
    d1 = r.json()
    assert d1["correo"] == "ana.lopez@empresa.com"
    assert d1["grupo_id"] == str(gid1) and d1["activo"] is True

    r = await client.post("/recipients", headers=headers, json={"correo": "ANA.LOPEZ@empresa.com", "grupo_id": str(gid2)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE"

    r = await client.post("/recipients", headers=headers, json={"correo": "x@y.com", "grupo_id": str(_uuid.uuid4())})
    assert r.status_code == 404

    r = await client.post("/recipients", headers=headers, json={"correo": "beto@y.com", "grupo_id": str(gid2)})
    assert r.status_code == 201
    d2 = r.json()

    r = await client.get("/recipients", headers=headers)
    assert r.status_code == 200 and r.json()["total"] == 2
    r = await client.get(f"/recipients?grupo_id={gid1}", headers=headers)
    assert r.status_code == 200 and r.json()["total"] == 1
    assert r.json()["items"][0]["correo"] == "ana.lopez@empresa.com"

    from app.db.session import SessionLocal
    from app.models.instantanea import InstantaneaPhishing

    async with SessionLocal() as db:
        db.add(InstantaneaPhishing(org_id=org_id, destinatario_id=_uuid.UUID(d1["id_destinatarios"]),
                                   puntaje_phishing=100.0, nivel="alto"))
        await db.commit()
    r = await client.get(f"/recipients/{d1['id_destinatarios']}", headers=headers)
    assert r.status_code == 200, r.text
    det = r.json()
    assert len(det["historico"]) == 1
    assert float(det["historico"][0]["puntaje_phishing"]) == 100.0
    assert det["historico"][0]["nivel"] == "alto"

    r = await client.patch(f"/recipients/{d2['id_destinatarios']}", headers=headers,
                           json={"correo": "beto.nuevo@y.com", "grupo_id": str(gid1)})
    assert r.status_code == 200, r.text
    assert r.json()["correo"] == "beto.nuevo@y.com" and r.json()["grupo_id"] == str(gid1)

    r = await client.patch(f"/recipients/{d2['id_destinatarios']}", headers=headers,
                           json={"correo": "ana.lopez@empresa.com"})
    assert r.status_code == 409

    r = await client.patch(f"/recipients/{d2['id_destinatarios']}/deactivate", headers=headers)
    assert r.status_code == 200 and r.json()["activo"] is False
    r = await client.patch(f"/recipients/{d2['id_destinatarios']}/deactivate", headers=headers)
    assert r.status_code == 422

    r = await client.post("/recipients", headers=headers, json={"correo": "beto.nuevo@y.com", "grupo_id": str(gid1)})
    assert r.status_code == 409

    r = await client.get(f"/groups/{gid1}", headers=headers)
    assert r.json()["metricas"]["destinatarios_activos"] == 1

    _, tok_analista = await _crear_analista(client, reg_a["org_id"])
    h_analista = {"Authorization": f"Bearer {tok_analista}"}
    r = await client.get("/recipients", headers=h_analista)
    assert r.status_code == 200 and r.json()["total"] == 2
    r = await client.post("/recipients", headers=h_analista, json={"correo": "z@z.com", "grupo_id": str(gid1)})
    assert r.status_code == 403

@pytest.mark.asyncio
async def test_destinatarios_import_csv(client, integration_guard):
    """CSV: mezcla de válidos, duplicados e inválidos; re-import dedupe contra la org; encabezados malos → 422."""
    _, tok_a = await _org_con_token(client, "csv")
    headers = {"Authorization": f"Bearer {tok_a}"}
    await _crear_grupo(client, tok_a, "Soporte")
    await _crear_grupo(client, tok_a, "Ventas")

    csv_1 = (
        "correo,grupo\n"
        "a1@x.com,Soporte\n"
        "A1@x.com,Ventas\n"
        "no-es-correo,Soporte\n"
        "nuevo@x.com,Contabilidad\n"
        "b2@x.com,Ventas\n"
        "\n"
    )
    r = await client.post("/recipients/import", headers=headers,
                          files={"file": ("destinatarios.csv", csv_1.encode("utf-8"), "text/csv")})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["total_filas"] == 5
    assert data["creados"] == 2
    assert data["duplicados"] == 1
    assert data["invalidos"] == 2
    assert len(data["errores"]) == 3

    r = await client.post("/recipients/import", headers=headers,
                          files={"file": ("destinatarios.csv", csv_1.encode("utf-8"), "text/csv")})
    assert r.status_code == 201
    data2 = r.json()
    assert data2["creados"] == 0
    assert data2["duplicados"] == 3

    r = await client.post("/recipients/import", headers=headers,
                          files={"file": ("mal.csv", b"email,grupo\na@x.com,Soporte\n", "text/csv")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"

    r = await client.post("/recipients/import", headers=headers,
                          files={"file": ("vacio.csv", b"", "text/csv")})
    assert r.status_code == 422

    r = await client.get("/recipients", headers=headers)
    assert r.json()["total"] == 2
    correos = {i["correo"] for i in r.json()["items"]}
    assert correos == {"a1@x.com", "b2@x.com"}

@pytest.mark.asyncio
async def test_aislamiento_multi_tenant_destinatarios(client, integration_guard):
    """La org B no puede leer/editar destinatarios de la org A, ni usar grupos ajenos en PATCH."""
    _, tok_a = await _org_con_token(client, "isoD")
    reg_b, tok_b = await _org_con_token(client, "isoE")
    h_b = {"Authorization": f"Bearer {tok_b}"}

    g_a = await _crear_grupo(client, tok_a, "Grupo A")
    r = await client.post("/recipients", headers={"Authorization": f"Bearer {tok_a}"},
                          json={"correo": "privado@a.com", "grupo_id": g_a["id_grupos"]})
    assert r.status_code == 201
    d_a = r.json()

    r = await client.get(f"/recipients/{d_a['id_destinatarios']}", headers=h_b)
    assert r.status_code == 404
    r = await client.patch(f"/recipients/{d_a['id_destinatarios']}", headers=h_b, json={"correo": "hack@b.com"})
    assert r.status_code == 404
    r = await client.patch(f"/recipients/{d_a['id_destinatarios']}/deactivate", headers=h_b)
    assert r.status_code == 404

    r = await client.get("/recipients", headers=h_b)
    correos_b = {i["correo"] for i in r.json()["items"]}
    assert "privado@a.com" not in correos_b

    g_b = await _crear_grupo(client, tok_b, "Grupo B")
    r = await client.post("/recipients", headers=h_b, json={"correo": "privado@a.com", "grupo_id": g_b["id_grupos"]})
    assert r.status_code == 201, r.text

    r = await client.patch(f"/recipients/{d_a['id_destinatarios']}", headers={"Authorization": f"Bearer {tok_a}"},
                           json={"grupo_id": g_b["id_grupos"]})
    assert r.status_code == 404
