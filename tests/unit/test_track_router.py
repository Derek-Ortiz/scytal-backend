from app.routers import track
from app.services.clonador_service import ACCION_FORM

def test_insertar_token_action_doble_comilla():
    html = '<html><form action="/track/submit" method="post"><input name="password"></form></html>'
    out = track.insertar_token_action(html, "abc123")
    assert 'action="/track/submit?t=abc123"' in out
    assert 'action="/track/submit"' not in out
    assert '<input name="password">' in out

def test_insertar_token_action_comilla_simple():
    html = "<form action='/track/submit'></form>"
    assert "action='/track/submit?t=xyz'" in track.insertar_token_action(html, "xyz")

def test_insertar_token_action_no_duplica_si_ya_lleva_token():
    """Servir la landing dos veces no debe acumular ?t=... (el HTML en BD no se toca)."""
    html = '<form action="/track/submit?t=original"></form>'
    out = track.insertar_token_action(html, "nuevo")
    assert out == html
    assert out.count("?t=") == 1

def test_insertar_token_action_sin_form_no_cambia_nada():
    html = "<html><body><p>Sin formularios</p></body></html>"
    assert track.insertar_token_action(html, "tok") == html

def test_marcador_del_clonador_es_el_esperado():
    """Guardia contra deriva: el marcador que guarda el clonador es el que /track reescribe."""
    assert ACCION_FORM == "/track/submit"

def test_pixel_es_gif_1x1():
    assert track.PIXEL_1X1.startswith(b"GIF89a")
    assert len(track.PIXEL_1X1) < 100

def test_awareness_sin_scripts_ni_recursos_externos():
    bajo = track.AWARENESS_HTML.lower()
    assert "<script" not in bajo
    assert "http://" not in bajo and "https://" not in bajo
    assert "simulación de phishing" in bajo
