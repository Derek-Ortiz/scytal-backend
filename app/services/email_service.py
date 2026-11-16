"""Envío de correo SMTP con reintentos y delay entre mensajes (§4.4, decisión de envío).

- send_email: un correo; reintenta SMTP_RETRY_ATTEMPTS veces con SMTP_RETRY_DELAY_SECONDS entre intentos.
- send_many: lote con SMTP_BULK_DELAY_SECONDS entre correos (para campañas/feedback, evita bloqueo del SMTP).

Fail-soft: un fallo de correo NUNCA rompe la petición HTTP; se registra en log y se devuelve False
(el router decide si informarlo al cliente, p. ej. correo_enviado=false en la invitación).
"""
import asyncio
import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import get_settings
from app.core.logging import log_event

LOG = logging.getLogger("scytal")


def _build_message(from_addr: str, to_addr: str, asunto: str, cuerpo_texto: str, cuerpo_html: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = asunto
    msg.set_content(cuerpo_texto)
    if cuerpo_html:
        msg.add_alternative(cuerpo_html, subtype="html")
    return msg


async def send_email(
    to_addr: str, asunto: str, cuerpo_texto: str, cuerpo_html: str | None = None, *, request_id: str | None = None
) -> bool:
    s = get_settings()
    msg = _build_message(s.SMTP_FROM, to_addr, asunto, cuerpo_texto, cuerpo_html)
    last_error = ""
    for intento in range(1, max(1, s.SMTP_RETRY_ATTEMPTS) + 1):
        try:
            await aiosmtplib.send(
                msg,
                hostname=s.SMTP_HOST,
                port=s.SMTP_PORT,
                username=s.SMTP_USER or None,
                password=s.SMTP_PASSWORD or None,
                start_tls=s.SMTP_USE_TLS,
            )
            log_event("email_sent", request_id=request_id, to=to_addr, subject=asunto)
            return True
        except Exception as e:  # noqa: BLE001 — SMTP es externo, cualquier fallo es reintetable
            last_error = str(e)
            log_event("email_retry", request_id=request_id, to=to_addr, attempt=intento, error=last_error[:200])
            if intento <= s.SMTP_RETRY_ATTEMPTS:
                await asyncio.sleep(s.SMTP_RETRY_DELAY_SECONDS)
    LOG.error("email_send_failed", extra={"to": to_addr, "subject": asunto, "error": last_error[:200], "request_id": request_id})
    return False


async def send_many(
    items: list[tuple[str, str, str, str | None]], *, request_id: str | None = None
) -> tuple[int, int]:
    """Envía un lote: [(to, asunto, texto, html), ...] con delay entre mensajes. Retorna (ok, fallos)."""
    s = get_settings()
    ok = 0
    fallos = 0
    for i, (to, asunto, texto, html) in enumerate(items):
        if i > 0 and s.SMTP_BULK_DELAY_SECONDS > 0:
            await asyncio.sleep(s.SMTP_BULK_DELAY_SECONDS)
        if await send_email(to, asunto, texto, html, request_id=request_id):
            ok += 1
        else:
            fallos += 1
    return ok, fallos
