"""Generación de imágenes QR (canal anónimo por zonas) — parte pura, sin BD."""
import base64
import io

import qrcode


def generar_qr_base64(url: str) -> str:
    """PNG del QR en base64 puro (sin prefijo data:; el frontend decide cómo mostrarlo)."""
    img = qrcode.make(url, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
