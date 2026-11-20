import pytest

from app.services import clonador_service as cs

@pytest.mark.parametrize("ip,esperado", [
    ("127.0.0.1", True),
    ("::1", True),
    ("10.1.2.3", True),
    ("192.168.0.20", True),
    ("172.16.9.9", True),
    ("169.254.169.254", True),
    ("fe80::1", True),
    ("224.0.0.1", True),
    ("192.0.2.1", True),
    ("8.8.8.8", False),
    ("93.184.216.34", False),
    ("2606:4700:4700::1111", False),
    ("no-es-ip", True),
])
def test_ip_bloqueada(ip, esperado):
    assert cs._ip_bloqueada(ip) is esperado

def test_url_valida_esquemas():
    with pytest.raises(ValueError):
        cs._url_valida("ftp://ejemplo.com/x")
    with pytest.raises(ValueError):
        cs._url_valida("file:///etc/passwd")
    with pytest.raises(ValueError):
        cs._url_valida("sin-esquema.com")
    p = cs._url_valida("https://portal.empresa.com/login?next=/home")
    assert p.scheme == "https" and p.hostname == "portal.empresa.com"

def test_necesita_render_false_con_contenido_real():
    html = ("<html><body><h1>Banco Ejemplo</h1><form><input type='password' name='pw'>"
            "<button>Entrar</button></form><p>Portal de empleados, use su clave de red.</p>"
            "</body></html>")
    assert cs.necesita_render(html) is False

def test_necesita_render_true_para_shell_react():
    shell = ("<html><head><script src='/static/js/main.a1.js'></script>"
             "<script src='/static/js/chunk.b2.js'></script></head>"
             "<body><div id='root'></div></body></html>")
    assert cs.necesita_render(shell) is True

def test_necesita_render_true_para_next():
    shell = "<html><body><div id='__next'></div><script src='/_next/static.js'></script></body></html>"
    assert cs.necesita_render(shell) is True

PAGINA = (
    '<html><head><title>Login</title>'
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
    '<meta http-equiv="refresh" content="5;url=/renueva">'
    '<base href="https://original.com/old/">'
    '<script src="/app.js"></script>'
    '<link rel="stylesheet" href="/css/estilos.css">'
    '<style>body{background:url(/img/fondo.png)}</style>'
    '</head><body>'
    '<img src="/img/logo.png" onerror="robar()">'
    '<a href="/recuperar" onclick="robar()">Olvidé mi clave</a>'
    '<a href="javascript:click_robo()" id="trampa">Enlace</a>'
    '<iframe src="https://tercero.com/frame"></iframe>'
    '<form action="/signin" method="get">'
    '<input name="usuario" type="text"><input name="clave" type="password">'
    '<button>Entrar</button></form>'
    '</body></html>'
)

@pytest.fixture
def procesada() -> str:
    return cs.procesar_html(PAGINA, "https://original.com/login")

def test_elimina_scripts_iframes_base_y_meta_peligrosos(procesada):
    assert "<script" not in procesada
    assert "<iframe" not in procesada
    assert "<base" not in procesada
    assert "Content-Security-Policy" not in procesada
    assert "http-equiv=\"refresh\"" not in procesada

def test_elimina_atributos_on_y_javascript(procesada):
    assert "onerror" not in procesada and "onclick" not in procesada
    assert "javascript:click_robo()" not in procesada
    assert 'href="#"' in procesada

def test_absolutiza_recursos_contra_url_final(procesada):
    assert 'src="https://original.com/img/logo.png"' in procesada
    assert 'href="https://original.com/css/estilos.css"' in procesada
    assert 'url(https://original.com/img/fondo.png)' in procesada
    assert 'href="https://original.com/recuperar"' in procesada

def test_forms_apuntan_a_track_submit(procesada):
    assert 'action="/track/submit"' in procesada
    assert 'method="post"' in procesada
    assert 'action="/signin"' not in procesada

def test_leyenda_con_leyenda_true():
    out = cs.procesar_html(PAGINA, "https://original.com/login", leyenda=True)
    assert "PÁGINA DE PRUEBA" in out

def test_imports_sin_leyenda_por_ahora():
    out = cs.procesar_html(PAGINA, "https://original.com/login")
    assert "PÁGINA DE PRUEBA" not in out

def test_inyecta_form_minimo_si_no_hay_password():
    html = "<html><body><h1>Solo texto informativo</h1></body></html>"
    out = cs.procesar_html(html, "https://x.com/")
    assert out.count('action="/track/submit"') == 1
    assert 'type="password"' in out

def test_no_duplica_leyenda_si_la_trae():
    html = "<html><body><p>página de prueba</p><form><input type='password'></form></body></html>"
    out = cs.procesar_html(html, "https://x.com/", leyenda=True)
    total = out.lower().count("página de prueba")
    assert total == 1

def test_fragmento_sin_body_no_explota():
    out = cs.procesar_html("<p>hola <script>malo()</script></p>", "https://x.com/", leyenda=True)
    assert "<script" not in out and "PÁGINA DE PRUEBA" in out

def test_absolutiza_srcset():
    html = ('<html><body><img srcset="/img/a.png 1x, /img/b.png 2x" '
            'data-srcset="/img/c.png 1x, https://cdn.com/d.png 2x"></body></html>')
    out = cs.procesar_html(html, "https://x.com/pag")
    assert "https://x.com/img/a.png 1x" in out and "https://x.com/img/b.png 2x" in out
    assert "https://x.com/img/c.png 1x" in out and "https://cdn.com/d.png 2x" in out

def test_dominio_de_url():
    assert cs._dominio("https://portal.banco.com/login?x=1") == "portal.banco.com"

def test_marcadores_del_correo_importado():
    assert "{{enlace}}" in cs.CONTENIDO_IMPORTADO and "{{pixel}}" in cs.CONTENIDO_IMPORTADO

def _red_css(monkeypatch, hojas: dict, tipo: str = "text/css"):
    """MockTransport para las hojas CSS + resolver DNS falso (IP pública, sin red real)."""
    import httpx

    async def _ips_publicas(host: str) -> list[str]:
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in hojas:
            return httpx.Response(200, headers={"content-type": tipo}, text=hojas[request.url.path])
        return httpx.Response(404, headers={"content-type": "text/plain"}, text="nope")

    monkeypatch.setattr(cs, "_ips_de_host", _ips_publicas)
    monkeypatch.setattr(
        cs, "_cliente",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False, timeout=5),
    )

@pytest.mark.asyncio
async def test_inlinea_hoja_externa(monkeypatch):
    _red_css(monkeypatch, {"/css/estilos.css": "body{background:url(/img/f.png)}"})
    html = '<html><head><link rel="stylesheet" href="/css/estilos.css"></head><body><p>x</p></body></html>'
    out = await cs.inlinar_css(html, "https://x.com/pag")
    assert "<link" not in out
    assert "<style" in out and "data-fuente" in out
    assert "https://x.com/img/f.png" in out

@pytest.mark.asyncio
async def test_import_anidado_absolutiza_contra_su_propia_hoja(monkeypatch):
    _red_css(monkeypatch, {
        "/css/main.css": '@import "tema.css";',
        "/css/tema.css": ".logo{background:url(logo.png)}",
    })
    html = '<html><head><link rel="stylesheet" href="/css/main.css"></head><body></body></html>'
    out = await cs.inlinar_css(html, "https://x.com/")
    assert "<link" not in out and "@import" not in out
    assert "https://x.com/css/logo.png" in out

@pytest.mark.asyncio
async def test_hoja_404_conserva_link(monkeypatch):
    _red_css(monkeypatch, {})
    html = '<html><head><link rel="stylesheet" href="/css/falta.css"></head><body></body></html>'
    out = await cs.inlinar_css(html, "https://x.com/")
    assert "/css/falta.css" in out
    assert "<style" not in out

@pytest.mark.asyncio
async def test_hoja_no_css_conserva_link(monkeypatch):
    _red_css(monkeypatch, {"/css/x.css": "{}"}, tipo="application/json")
    html = '<html><head><link rel="stylesheet" href="/css/x.css"></head><body></body></html>'
    out = await cs.inlinar_css(html, "https://x.com/")
    assert "<style" not in out and "/css/x.css" in out

@pytest.mark.asyncio
async def test_hoja_con_style_cerrado_no_se_inlinea(monkeypatch):
    _red_css(monkeypatch, {"/css/malvado.css": ".a{}</style><script>robo()</script>"})
    html = '<html><head><link rel="stylesheet" href="/css/malvado.css"></head><body></body></html>'
    out = await cs.inlinar_css(html, "https://x.com/")
    assert "<style" not in out and "/css/malvado.css" in out

@pytest.mark.asyncio
async def test_hoja_demasiado_grande_conserva_link(monkeypatch):
    grande = "a{" + "0" * (cs.MAX_CSS_POR_HOJA + 10) + "}"
    _red_css(monkeypatch, {"/css/grande.css": grande})
    html = '<html><head><link rel="stylesheet" href="/css/grande.css"></head><body></body></html>'
    out = await cs.inlinar_css(html, "https://x.com/")
    assert "<style" not in out and "/css/grande.css" in out

@pytest.mark.asyncio
async def test_presupuesto_total_de_css(monkeypatch):
    grande = "a{" + "0" * (cs.MAX_CSS_POR_HOJA - 3) + "}"
    media = "b{" + "0" * 499_998 + "}"
    _red_css(monkeypatch, {"/css/a.css": grande, "/css/b.css": media})
    html = ('<html><head><link rel="stylesheet" href="/css/a.css">'
            '<link rel="stylesheet" href="/css/b.css"></head><body></body></html>')
    out = await cs.inlinar_css(html, "https://x.com/")
    assert out.count("<style") == 1
    assert media not in out and "/css/b.css" in out

def test_css_a_absoluto_puro():
    css = ".a{background:url(logo.png)} .b{background:url(https://cdn.com/x.png)}"
    out = cs._css_a_absoluto(css, "https://x.com/css/tema.css")
    assert "url(https://x.com/css/logo.png)" in out
    assert "url(https://cdn.com/x.png)" in out
    assert cs._css_a_absoluto(".c{mask:url(data:image/png;base64,AA)}", "https://x.com/") == \
        ".c{mask:url(data:image/png;base64,AA)}"
