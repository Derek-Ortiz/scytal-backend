"""Pruebas unitarias del cálculo del índice de phishing (§7) — parte pura de maturity_service."""
from app.services.maturity_service import calcular_puntaje_phishing, nivel_phishing


def test_sin_interaccion_da_100_alto():
    # Decisión del usuario: quien nunca interactúa SÍ cuenta y obtiene el índice máximo.
    assert calcular_puntaje_phishing(False, False, False) == 100.0
    assert nivel_phishing(100.0) == "alto"


def test_solo_abrio():
    assert calcular_puntaje_phishing(True, False, False) == 75.0
    assert nivel_phishing(75.0) == "medio"


def test_abrio_y_clico():
    assert calcular_puntaje_phishing(True, True, False) == 50.0
    assert nivel_phishing(50.0) == "bajo"


def test_cayo_completo():
    assert calcular_puntaje_phishing(True, True, True) == 0.0
    assert nivel_phishing(0.0) == "critico"


def test_solo_envio_datos():
    # Enviar datos pesa 50%: sin abrir ni clicar pero enviando → 50
    assert calcular_puntaje_phishing(False, False, True) == 50.0
