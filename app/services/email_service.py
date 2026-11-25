import asyncio
import logging
from email.message import EmailMessage
from functools import lru_cache

import aiosmtplib

from app.core.config import get_settings
from app.core.logging import log_event

LOG = logging.getLogger("scytal")

PROVEEDORES_VALIDOS = ("smtp", "ses")


@lru_cache
def _ses_client(region: str):
    """Cliente SES v2. Sin llaves en .env: boto3 usa la cadena por defecto
    (rol de la instancia EC2 / LabInstanceProfile, variables AWS_* o ~/.aws)."""
    import boto3  # import diferido: solo se requiere si EMAIL_PROVIDER=ses

    return boto3.client("sesv2", region_name=region)


async def _enviar_smtp(msg: EmailMessage) -> None:
    s = get_settings()
    await aiosmtplib.send(
        msg,
        hostname=s.SMTP_HOST,
        port=s.SMTP_PORT,
        username=s.SMTP_USER or None,
        password=s.SMTP_PASSWORD or None,
        start_tls=s.SMTP_USE_TLS,
    )


async def _enviar_ses(msg: EmailMessage) -> None:
    s = get_settings()
    params: dict = {
        "FromEmailAddress": msg["From"],
        "Destination": {"ToAddresses": [msg["To"]]},
        "Content": {"Raw": {"Data": msg.as_bytes()}},
    }
    if s.SES_CONFIGURATION_SET:
        params["ConfigurationSetName"] = s.SES_CONFIGURATION_SET
    cliente = _ses_client(s.AWS_REGION)
    # boto3 es síncrono: se ejecuta en un hilo para no bloquear el event loop.
    await asyncio.to_thread(cliente.send_email, **params)


def _proveedor() -> str:
    proveedor = (get_settings().EMAIL_PROVIDER or "smtp").strip().lower()
    if proveedor not in PROVEEDORES_VALIDOS:
        raise ValueError(f"EMAIL_PROVIDER inválido: {proveedor!r} (usa smtp o ses)")
    return proveedor


async def _entregar(msg: EmailMessage) -> None:
    if _proveedor() == "ses":
        await _enviar_ses(msg)
    else:
        await _enviar_smtp(msg)

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
    msg = _build_message(s.EMAIL_FROM or s.SMTP_FROM, to_addr, asunto, cuerpo_texto, cuerpo_html)
    last_error = ""
    for intento in range(1, max(1, s.SMTP_RETRY_ATTEMPTS) + 1):
        try:
            await _entregar(msg)
            log_event("email_sent", request_id=request_id, to=to_addr, subject=asunto, provider=_proveedor())
            return True
        except Exception as e:
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

async def send_many_detailed(
    items: list[tuple[str, str, str, str | None]], *, request_id: str | None = None
) -> list[bool]:
    """Como send_many pero retorna el resultado INDIVIDUAL de cada correo ([True/False por ítem]).

    Lo usa el despacho de campañas: cada éxito estampa enviado_en de su propia fila de token,
    así un fallo del proveedor no marca como enviados los correos que sí salieron.
    """
    s = get_settings()
    resultados: list[bool] = []
    for i, (to, asunto, texto, html) in enumerate(items):
        if i > 0 and s.SMTP_BULK_DELAY_SECONDS > 0:
            await asyncio.sleep(s.SMTP_BULK_DELAY_SECONDS)
        resultados.append(await send_email(to, asunto, texto, html, request_id=request_id))
    return resultados
