"""Cálculo del índice de phishing (§7): 25% no abrir + 25% no dar clic + 50% no enviar datos.

Parte pura (probable sin BD). La parte de BD (persistir instantáneas, alertas) llega con la Fase 6.
Umbrales de nivel_madurez (decisión propuesta, ajustable):
    alto >= 90 · medio >= 65 · bajo >= 35 · critico < 35
"""


def calcular_puntaje_phishing(abrio: bool, clico: bool, envio: bool) -> float:
    """Puntaje de resistencia 0-100. Mayor = más resistente. Quien nunca interactúa obtiene 100."""
    puntaje = 0.0
    if not abrio:
        puntaje += 25
    if not clico:
        puntaje += 25
    if not envio:
        puntaje += 50
    return puntaje


def nivel_phishing(puntaje: float) -> str:
    if puntaje >= 90:
        return "alto"
    if puntaje >= 65:
        return "medio"
    if puntaje >= 35:
        return "bajo"
    return "critico"
