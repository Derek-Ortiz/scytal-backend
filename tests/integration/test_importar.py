"""Pruebas de integración POST /templates/importar (Opción A + B).

La red se simula con httpx.MockTransport (inyectado en clonador_service._cliente) y el
resolver DNS con un _ips_de_host falso (IP pública) — así se ejercita el pipeline completo
sin salir de la máquina. El guardián SSRF REAL se prueba aparte con hosts loopback/metadata.
"""
import httpx
import pytest

pytestmark = pytest.mark.integration

from app.services import clonador_service  # noqa: E402
from tests.integration.test_groups import _crear_analista, _org_con_token  # noqa: E402

PAGINA = (
    '<html><head><title>Portal internos</title>'
    '<script src="/static/app.js"></script>'
    '<link rel="stylesheet" href="/css/portal.css" integrity="sha384-zzz">'
    '</head><body>'
    '<h1>Portal de empleados</h1>'
    '<img src="/img/logo.png" onerror="robar()">'
    '<form action="/signin" method="get">'
    '<input name="usuario" type="text"><input name="clave" type="password">'
    '<button>Entrar</button></form>'
    '</body></html>'
)

SHELL_SPA = (
    '<html><head><script src="/static/js/main.1.js"></script>'
    '<script src="/static/js/chunk.2.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)

RENDERIZADO = (
    '<html><head><link rel="stylesheet" href="/css/app.css"></head>'
    '<body><div id="root"><form action="/api/auth" method="post">'
    '<input name="usuario" type="text"><input name="clave" type="password">'
    '</form></div></body></html>'
)


def _transporte() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirige":
            return httpx.Response(302, headers={"location": "/login"})
        if request.url.path == "/login":
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGINA)
        if request.url.path == "/spa":
            return httpx.Response(200, headers={"content-type": "text/html"}, text=SHELL_SPA)
        if request.url.path == "/muere":
            return httpx.Response(500)
        if request.url.path == "/nohtml":
            return httpx.Response(200, headers={"content-type": "application/json"}, text='{"hola": 1}')
        if request.url.path == "/grande":
            return httpx.Response(200, headers={"content-type": "text/html"}, text="x" * (clonador_service.MAX_TAMANO + 1))
        return httpx.Response(404, headers={"content-type": "text/html"}, text="<html></html>")

    return httpx.MockTransport(handler)


@pytest.fixture
def red_falsa(monkeypatch):
    """Inyecta transporte de prueba + resolver DNS falso (IP pública para todos los hosts)."""

    async def _ips_publicas(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(clonador_service, "_ips_de_host", _ips_publicas)
    monkeypatch.setattr(
        clonador_service, "_cliente",
        lambda: httpx.AsyncClient(transport=_transporte(), follow_redirects=False, timeout=5),
    )


@pytest.mark.asyncio
async def test_importar_flujo_estatico_con_redirect(client, integration_guard, red_falsa):
    reg, tok = await _org_con_token(client, "import")
    headers = {"Authorization": f"Bearer {tok}"}

    r = await client.post("/templates/importar", headers=headers, json={
        "url": "https://portal.falso.com/redirige", "nombre": "Portal empleados",
    })
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["nombre"] == "Portal empleados"
    assert p["asunto"] == "Verificación de seguridad de portal.falso.com"  # autogenerado
    assert p["canal"] == "correo" and p["perfil"] == "corporativo"  # defaults
    assert p["contenido_html"].startswith("<div") and "{{enlace}}" in p["contenido_html"]

    landing = p["landing_html"]
    assert "PÁGINA DE PRUEBA" in landing                     # leyenda obligatoria
    assert 'action="/track/submit"' in landing              # form capturado
    assert 'method="post"' in landing
    assert "<script" not in landing                         # snapshot sin vida
    assert "onerror" not in landing
    assert 'src="https://portal.falso.com/img/logo.png"' in landing   # absolutizado
    assert 'href="https://portal.falso.com/css/portal.css"' in landing
    assert "integrity" not in landing                       # integridad soltada

    # en_uso False y visible en el listado
    r = await client.get("/templates", headers=headers)
    assert any(i["nombre"] == "Portal empleados" for i in r.json()["items"])


@pytest.mark.asyncio
async def test_importar_fallback_render_b(client, integration_guard, red_falsa, monkeypatch):
    """Carcasa SPA (A) → dispara Opción B (mock) → procesa el DOM renderizado."""
    reg, tok = await _org_con_token(client, "importb")
    headers = {"Authorization": f"Bearer {tok}"}

    llamadas = []

    async def _render_falso(url: str) -> str:
        llamadas.append(url)
        return RENDERIZADO

    monkeypatch.setattr(clonador_service, "renderizar_con_navegador", _render_falso)

    r = await client.post("/templates/importar", headers=headers, json={
        "url": "https://spa.falso.com/spa",
    })
    assert r.status_code == 201, r.text
    assert llamadas == ["https://spa.falso.com/spa"]  # B recibió la URL final
    landing = r.json()["landing_html"]
    assert 'action="/track/submit"' in landing           # form del DOM renderizado capturado
    assert "PÁGINA DE PRUEBA" in landing
    assert "<script" not in landing


@pytest.mark.asyncio
async def test_importar_render_b_real_si_chromium(client, integration_guard):
    """Opción B REAL con Chromium local (se salta si no está instalado)."""
    pytest.importorskip("playwright")
    try:
        html = await clonador_service.renderizar_con_navegador(
            "data:text/html,<html><body><div id='root'><form>"
            "<input name='u'><input name='p' type='password'></form></div></body></html>"
        )
    except ValueError as e:
        if "Chromium" in str(e):
            pytest.skip(f"Chromium no disponible: {e}")
        raise
    assert 'type="password"' in html           # Chromium produjo el DOM (el JS está vivo)
    procesada = clonador_service.procesar_html(html, "https://x.com/")
    assert 'action="/track/submit"' in procesada  # el pipeline la convertiría en plantilla


@pytest.mark.asyncio
async def test_importar_errores(client, integration_guard, red_falsa):
    reg, tok = await _org_con_token(client, "impe")
    headers = {"Authorization": f"Bearer {tok}"}

    # 404 (contenido default del handler) → el clon del 404 HTML sí es válido; sin cuerpo válido:
    r = await client.post("/templates/importar", headers=headers, json={"url": "https://x.falso.com/muere"})
    assert r.status_code == 422 and "500" in r.json()["error"]["message"]
    r = await client.post("/templates/importar", headers=headers, json={"url": "https://x.falso.com/nohtml"})
    assert r.status_code == 422 and "HTML" in r.json()["error"]["message"]
    r = await client.post("/templates/importar", headers=headers, json={"url": "https://x.falso.com/grande"})
    assert r.status_code == 422 and "MB" in r.json()["error"]["message"]
    # esquema prohibido → 422
    r = await client.post("/templates/importar", headers=headers, json={"url": "ftp://x.falso.com/x"})
    assert r.status_code == 422
    # canal inválido → 422 (schema)
    r = await client.post("/templates/importar", headers=headers, json={"url": "https://x.falso.com/login", "canal": "sms"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_importar_bloquea_ssrf_real(client, integration_guard):
    """Guardas SSRF con resolver REAL: loopback y metadata de nube quedan fuera (sin red)."""
    reg, tok = await _org_con_token(client, "impr")
    headers = {"Authorization": f"Bearer {tok}"}
    for url_mala in (
        "http://127.0.0.1:8000/health",
        "http://localhost/secreto",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.10/admin",
    ):
        r = await client.post("/templates/importar", headers=headers, json={"url": url_mala})
        assert r.status_code == 422, url_mala
        assert "interna" in r.json()["error"]["message"]


@pytest.mark.asyncio
async def test_importar_permisos(client, integration_guard):
    reg, tok = await _org_con_token(client, "impp")
    _, tok_analista = await _crear_analista(client, reg["org_id"])
    r = await client.post("/templates/importar", headers={"Authorization": f"Bearer {tok_analista}"}, json={
        "url": "https://x.falso.com/login",
    })
    assert r.status_code == 403
    r = await client.post("/templates/importar", json={"url": "https://x.falso.com/login"})
    assert r.status_code == 401
