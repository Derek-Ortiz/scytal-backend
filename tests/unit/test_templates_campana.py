"""Pruebas unitarias de Fase 3 sin BD: leyenda de landing, render de correo, validaciones
Pydantic de plantillas/canales y generación de QR."""
import base64

import pytest
from pydantic import ValidationError

from app.schemas.campana import CampanaChannelsRequest
from app.schemas.plantilla import PlantillaCreateRequest
from app.services.campana_service import render_correo
from app.services.plantilla_service import LEYENDA, aplicar_leyenda
from app.services.qr_service import generar_qr_base64


# ---- Leyenda obligatoria de landing ----

def test_leyenda_se_anade_si_falta():
    html = "<html><body><h1>Entra a tu cuenta</h1></body></html>"
    out = aplicar_leyenda(html)
    assert LEYENDA in out
    assert out.endswith("</div>")


def test_leyenda_no_se_duplica_si_ya_esta():
    html = f"<html><body>Formulario<div>PÁGINA DE PRUEBA ya avisada</div></body></html>"
    assert aplicar_leyenda(html) == html


def test_leyenda_case_insensitive():
    html = "<p>página de prueba</p>"
    assert aplicar_leyenda(html) == html


# ---- render_correo (marcadores {{enlace}} / {{pixel}}) ----

BASE = "http://localhost:3000"
TOKEN = "a" * 64


def test_render_sustituye_enlace_y_pixel():
    html = '<p>Entra: <a href="{{enlace}}">aquí</a></p>{{pixel}}'
    out = render_correo(html, TOKEN, BASE)
    assert f"{BASE}/track/click?t={TOKEN}" in out
    assert f'<img src="{BASE}/track/open?t={TOKEN}"' in out
    assert "{{enlace}}" not in out and "{{pixel}}" not in out


def test_render_anade_enlace_y_pixel_si_faltan():
    out = render_correo("<p>Mensaje sin marcadores</p>", TOKEN, BASE)
    assert f"{BASE}/track/click?t={TOKEN}" in out  # enlace añadido
    assert f"{BASE}/track/open?t={TOKEN}" in out   # pixel añadido


def test_render_normaliza_base_con_slash_final():
    out = render_correo("{{pixel}}", TOKEN, BASE + "/")
    assert f'{BASE}/track/open?t={TOKEN}"' in out
    assert "//track" not in out


# ---- Validaciones Pydantic (§5: canal=correo exige asunto) ----

def _datos_plantilla(**extra):
    datos = {
        "nombre": "Login falso", "perfil": "corporativo", "canal": "correo",
        "asunto": "Verifica tu cuenta", "contenido_html": "<p>hola {{enlace}}</p>",
        "landing_html": "<html></html>",
    }
    datos.update(extra)
    return datos


def test_plantilla_correo_sin_asunto_rechazada():
    with pytest.raises(ValidationError):
        PlantillaCreateRequest(**_datos_plantilla(asunto=None))


def test_plantilla_correo_con_asunto_aceptada():
    p = PlantillaCreateRequest(**_datos_plantilla())
    assert p.canal == "correo" and p.asunto == "Verifica tu cuenta"


def test_plantilla_qr_sin_asunto_aceptada():
    p = PlantillaCreateRequest(**_datos_plantilla(canal="qr", asunto=None))
    assert p.canal == "qr" and p.asunto is None


def test_plantilla_canal_invalido_rechazado():
    with pytest.raises(ValidationError):
        PlantillaCreateRequest(**_datos_plantilla(canal="sms"))


def test_plantilla_html_solo_espacios_rechazado():
    with pytest.raises(ValidationError):
        PlantillaCreateRequest(**_datos_plantilla(contenido_html="   "))


# ---- Canales de campaña ----

def test_canales_qr_sin_zonas_rechazado():
    with pytest.raises(ValidationError):
        CampanaChannelsRequest(canales=["correo", "qr"])


def test_canales_zonas_sin_qr_rechazado():
    with pytest.raises(ValidationError):
        CampanaChannelsRequest(canales=["correo"], zonas=["Recepción"])


def test_canales_validos_con_zonas():
    c = CampanaChannelsRequest(canales=["qr", "correo"], zonas=["Recepción", " Comedor "])
    assert c.zonas == ["Recepción", "Comedor"]  # trim aplicado


def test_canales_duplicados_rechazados():
    with pytest.raises(ValidationError):
        CampanaChannelsRequest(canales=["correo", "correo"])


def test_canales_zonas_duplicadas_rechazadas():
    with pytest.raises(ValidationError):
        CampanaChannelsRequest(canales=["qr"], zonas=["Recepción", "recepción"])


def test_canales_vacios_rechazados():
    with pytest.raises(ValidationError):
        CampanaChannelsRequest(canales=[])


# ---- QR ----

def test_qr_base64_es_png_valido():
    b64 = generar_qr_base64("http://localhost:3000/track/click?t=abc")
    crudos = base64.b64decode(b64)
    assert crudos[:8] == b"\x89PNG\r\n\x1a\n"  # firma PNG
