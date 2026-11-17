"""Pruebas unitarias del importador de plantillas por URL (Opción A + B, sin BD ni red)."""
import pytest

from app.services import clonador_service as cs


# ---- Guardas SSRF ----

@pytest.mark.parametrize("ip,esperado", [
    ("127.0.0.1", True),            # loopback
    ("::1", True),
    ("10.1.2.3", True),             # privada
    ("192.168.0.20", True),
    ("172.16.9.9", True),
    ("169.254.169.254", True),      # metadata de nubes (AWS/GCP/Azure)
    ("fe80::1", True),              # link-local
    ("224.0.0.1", True),            # multicast
    ("192.0.2.1", True),            # TEST-NET reservado (no global)
    ("8.8.8.8", False),
    ("93.184.216.34", False),
    ("2606:4700:4700::1111", False),
    ("no-es-ip", True),             # inválida → bloquear por defecto
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


# ---- Detección de carcasa SPA (decide Opción A vs Opción B) ----

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


# ---- procesar_html: el corazón de la Opción A ----

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
    assert 'href="#"' in procesada  # el enlace trampa queda neutralizado


def test_absolutiza_recursos_contra_url_final(procesada):
    assert 'src="https://original.com/img/logo.png"' in procesada
    assert 'href="https://original.com/css/estilos.css"' in procesada
    assert 'url(https://original.com/img/fondo.png)' in procesada  # CSS <style> inline
    assert 'href="https://original.com/recuperar"' in procesada


def test_forms_apuntan_a_track_submit(procesada):
    assert 'action="/track/submit"' in procesada
    assert 'method="post"' in procesada
    assert 'action="/signin"' not in procesada


def test_leyenda_obligatoria(procesada):
    assert "PÁGINA DE PRUEBA" in procesada


def test_inyecta_form_minimo_si_no_hay_password():
    html = "<html><body><h1>Solo texto informativo</h1></body></html>"
    out = cs.procesar_html(html, "https://x.com/")
    assert out.count('action="/track/submit"') == 1
    assert 'type="password"' in out  # el form mínimo captura credenciales


def test_no_duplica_leyenda_si_la_trae():
    html = "<html><body><p>página de prueba</p><form><input type='password'></form></body></html>"
    out = cs.procesar_html(html, "https://x.com/")
    total = out.lower().count("página de prueba")
    assert total == 1  # case-insensitive: no se añade una segunda


def test_fragmento_sin_body_no_explota():
    out = cs.procesar_html("<p>hola <script>malo()</script></p>", "https://x.com/")
    assert "<script" not in out and "PÁGINA DE PRUEBA" in out


# ---- Asunto/contenido generados para la plantilla importada ----

def test_dominio_de_url():
    assert cs._dominio("https://portal.banco.com/login?x=1") == "portal.banco.com"


def test_marcadores_del_correo_importado():
    # el cuerpo de correo generado debe traer {{enlace}} y {{pixel}}
    assert "{{enlace}}" in cs.CONTENIDO_IMPORTADO and "{{pixel}}" in cs.CONTENIDO_IMPORTADO
