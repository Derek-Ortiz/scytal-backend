import uuid as _uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.integration

from tests.integration.test_campaigns import (
    _agregar_destinatario, _crear_campana, _fila_token, _tokens_de,
)
from tests.integration.test_groups import _crear_grupo, _org_con_token
from tests.integration.test_templates import _crear_plantilla

LANDING_CON_FORM = (
    '<html><head><title>Login</title></head><body><h1>Inicia sesión</h1>'
    '<form action="/track/submit" method="post">'
    '<input name="username" /><input name="password" type="password" />'
    "<button>Entrar</button></form></body></html>"
)

@pytest.fixture
def correo_falso(monkeypatch):
    """Reemplaza el envío SMTP: captura los lotes y devuelve éxito individual."""
    from app.services import campana_service

    enviados: list[list[tuple]] = []

    async def _falso(lote, *, request_id=None):
        enviados.append(list(lote))
        return [True] * len(lote)

    monkeypatch.setattr(campana_service, "_enviar_lote", _falso)
    return enviados

@pytest.fixture(autouse=True)
async def _limpiar_rate_limit():
    """Limpia `rl:track:*` antes/después de cada prueba: la clave va por IP (compartida)."""
    from app.core.rate_limit import _get_redis

    async def _limpiar():
        r = _get_redis()
        if r is None:
            return
        try:
            claves = await r.keys("rl:track:*")
            if claves:
                await r.delete(*claves)
        except Exception:
            pass

    await _limpiar()
    yield
    await _limpiar()

async def _eventos(fila_id) -> list:
    from app.db.session import SessionLocal
    from app.models.tracking import EventoTracking

    async with SessionLocal() as db:
        res = await db.execute(select(EventoTracking).where(
            EventoTracking.destinatario_campana_id == fila_id
        ))
        return list(res.scalars().all())

async def _vencer_token(campana_id: str, correo: str) -> None:
    from app.db.session import SessionLocal
    from app.models.campana import DestinatarioCampana

    fila = await _fila_token(campana_id, correo)
    async with SessionLocal() as db:
        await db.execute(
            update(DestinatarioCampana)
            .where(DestinatarioCampana.id_destinatarios_campana == fila.id_destinatarios_campana)
            .values(expira_en=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        await db.commit()

async def _zona_de(campana_id: str, token_qr: str | None = None):
    from app.db.session import SessionLocal
    from app.models.qr_zona import CampanaQrZona

    async with SessionLocal() as db:
        q = select(CampanaQrZona).where(CampanaQrZona.campana_id == _uuid.UUID(campana_id))
        if token_qr is not None:
            q = q.where(CampanaQrZona.token_qr == token_qr)
        res = await db.execute(q)
        return res.scalars().first()

async def _campana_lanzada(client, *, canales: list[str], zonas: list[str] | None = None) -> tuple[str, str]:
    """(campana_id, token_admin) con 1 destinatario, plantilla con form y campaña activa."""
    _reg, tok = await _org_con_token(client, "track")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Oficina Central")
    p = await _crear_plantilla(client, tok, "Login falso", landing_html=LANDING_CON_FORM)
    await _agregar_destinatario(client, tok, g["id_grupos"], "ana@corp.local")
    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"], expiracion_horas=24)
    cid = c["id_campanas"]
    cuerpo: dict = {"canales": canales}
    if "qr" in canales:
        cuerpo["zonas"] = zonas or ["Recepción"]
    r = await client.post(f"/campaigns/{cid}/channels", headers=headers, json=cuerpo)
    assert r.status_code == 200, r.text
    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    return cid, tok

async def _token_qr(client, tok: str, cid: str) -> str:
    r = await client.get(f"/campaigns/{cid}/qr", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    return r.json()["zonas"][0]["url"].split("?t=")[1]

async def test_flujo_correo_completo(client, integration_guard, correo_falso):
    cid, _tok = await _campana_lanzada(client, canales=["correo"])
    toks = _tokens_de(correo_falso)
    assert len(toks) == 1
    t = toks[0]

    r = await client.get(f"/track/open?t={t}", headers={"User-Agent": "Victima/1.0"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/gif")
    assert r.content.startswith(b"GIF89a")
    fila = await _fila_token(cid, "ana@corp.local")
    assert fila.abierto_en is not None and fila.clic_en is None
    evs = await _eventos(fila.id_destinatarios_campana)
    assert [e.tipo for e in evs] == ["abierto"]
    assert evs[0].canal_origen == "correo" and evs[0].direccion_ip and evs[0].user_agent == "Victima/1.0"

    r = await client.get(f"/track/click?t={t}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/track/landing?t={t}"
    fila = await _fila_token(cid, "ana@corp.local")
    assert fila.clic_en is not None
    evs = await _eventos(fila.id_destinatarios_campana)
    assert sorted(e.tipo for e in evs) == ["abierto", "click"]

    r = await client.get(f"/track/landing?t={t}")
    assert r.status_code == 200
    assert f'action="/track/submit?t={t}"' in r.text
    assert 'action="/track/submit"' not in r.text
    assert "form-action 'self'" in r.headers["content-security-policy"]

    r = await client.post(
        f"/track/submit?t={t}", data={"username": "ana", "password": "secreto-no-guardar"},
        headers={"User-Agent": "Victima/1.0"}, follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/track/awareness")
    evs = await _eventos(fila.id_destinatarios_campana)
    subidos = [e for e in evs if e.tipo == "subido"]
    assert len(subidos) == 1
    assert subidos[0].user_agent == "Victima/1.0"
    assert "secreto-no-guardar" not in " ".join(
        str(getattr(subidos[0], c)) for c in ("tipo", "canal_origen", "direccion_ip", "user_agent")
    )

    r = await client.post(f"/track/submit?t={t}", json={"password": "otro-secreto"}, follow_redirects=False)
    assert r.status_code == 303
    evs = await _eventos(fila.id_destinatarios_campana)
    assert len([e for e in evs if e.tipo == "subido"]) == 2

    r = await client.get(f"/track/awareness?t={t}")
    assert r.status_code == 200 and "simulación de phishing" in r.text

async def test_token_vencido_respuesta_generica_sin_metricas(client, integration_guard, correo_falso):
    cid, _tok = await _campana_lanzada(client, canales=["correo"])
    t = _tokens_de(correo_falso)[0]
    await _vencer_token(cid, "ana@corp.local")

    r = await client.get(f"/track/open?t={t}")
    assert r.status_code == 200 and r.content.startswith(b"GIF89a")
    fila = await _fila_token(cid, "ana@corp.local")
    assert fila.abierto_en is None and fila.clic_en is None
    assert await _eventos(fila.id_destinatarios_campana) == []

    r = await client.get(f"/track/click?t={t}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/track/awareness")
    r = await client.get(f"/track/landing?t={t}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/track/awareness")
    r = await client.post(f"/track/submit?t={t}", data={"password": "x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/track/awareness")
    assert await _eventos((await _fila_token(cid, "ana@corp.local")).id_destinatarios_campana) == []

    desconocido = "ab" * 32
    vencido = await client.get(f"/track/click?t={t}", follow_redirects=False)
    inexistente = await client.get(f"/track/click?t={desconocido}", follow_redirects=False)
    ruta_vencido = urlsplit(vencido.headers["location"]).path
    ruta_inexistente = urlsplit(inexistente.headers["location"]).path
    assert vencido.status_code == inexistente.status_code
    assert ruta_vencido == ruta_inexistente == "/track/awareness"

async def test_qr_anonimo_fuera_del_embudo(client, integration_guard):
    cid, tok = await _campana_lanzada(client, canales=["qr"], zonas=["Recepción", "Comedor"])
    tq = await _token_qr(client, tok, cid)

    r = await client.get(f"/track/click?t={tq}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/track/landing?t={tq}"
    zona = await _zona_de(cid, tq)
    assert zona.clic_en is not None
    fila = await _fila_token(cid, "ana@corp.local")
    assert fila.clic_en is None and fila.abierto_en is None
    assert await _eventos(fila.id_destinatarios_campana) == []

    r = await client.get(f"/track/landing?t={tq}")
    assert r.status_code == 200 and f'action="/track/submit?t={tq}"' in r.text

    r = await client.post(f"/track/submit?t={tq}", data={"password": "secreto"}, follow_redirects=False)
    assert r.status_code == 303
    r = await client.get(f"/track/open?t={tq}")
    assert r.status_code == 200 and r.content.startswith(b"GIF89a")
    assert await _eventos((await _fila_token(cid, "ana@corp.local")).id_destinatarios_campana) == []

async def test_qr_invalido_hasta_lanzar_y_tras_cancelar(client, integration_guard):
    """expira_en NULL (sin lanzar) y tokens caducados (cancel) → misma respuesta genérica."""
    _reg, tok = await _org_con_token(client, "trackq")
    headers = {"Authorization": f"Bearer {tok}"}
    g = await _crear_grupo(client, tok, "Oficina")
    p = await _crear_plantilla(client, tok, "Login falso", landing_html=LANDING_CON_FORM)
    await _agregar_destinatario(client, tok, g["id_grupos"], "ana@corp.local")
    c = await _crear_campana(client, tok, g["id_grupos"], p["id_plantillas"])
    cid = c["id_campanas"]
    r = await client.post(f"/campaigns/{cid}/channels", headers=headers,
                          json={"canales": ["qr"], "zonas": ["Recepción"]})
    assert r.status_code == 200, r.text
    tq = await _token_qr(client, tok, cid)

    r = await client.get(f"/track/click?t={tq}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/track/awareness")
    assert (await _zona_de(cid, tq)).clic_en is None

    r = await client.post(f"/campaigns/{cid}/launch", headers=headers)
    assert r.status_code == 200, r.text
    r = await client.get(f"/track/click?t={tq}", follow_redirects=False)
    assert r.headers["location"] == f"/track/landing?t={tq}"
    assert (await _zona_de(cid, tq)).clic_en is not None

    r = await client.post(f"/campaigns/{cid}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    clic_previo = (await _zona_de(cid, tq)).clic_en
    r = await client.get(f"/track/click?t={tq}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/track/awareness")
    assert (await _zona_de(cid, tq)).clic_en == clic_previo

async def test_rate_limit_60_por_ip(client, integration_guard):
    for i in range(60):
        r = await client.get("/track/open")
        assert r.status_code == 200, f"solicitud {i} dentro de límite"
    r = await client.get("/track/open")
    assert r.status_code == 429
    assert r.headers.get("retry-after") == "60"
    assert r.json()["error"]["code"] == "RATE_LIMITED"
