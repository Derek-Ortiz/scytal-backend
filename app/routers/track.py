from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import check_limit
from app.db.session import get_db
from app.models.campana import Campana, DestinatarioCampana
from app.models.plantilla import Plantilla
from app.models.qr_zona import CampanaQrZona
from app.repositories import campana_repository as campana_repo
from app.repositories import qr_zona_repository as qr_repo
from app.repositories import tracking_repository as tracking_repo
from app.schemas.auth import error_payload
from app.services.clonador_service import ACCION_FORM

router = APIRouter(prefix="/track", tags=["track"])

LIMITE_POR_IP = 60
VENTANA_SEG = 60
RETRY_AFTER = {"Retry-After": str(VENTANA_SEG)}

PIXEL_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)

AWARENESS_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Simulación de phishing — Scytal</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; background:#0f172a; color:#e2e8f0;
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }
  main { max-width:34rem; margin:1.5rem; background:#1e293b; border:1px solid #334155;
         border-radius:12px; padding:2rem; }
  h1 { font-size:1.4rem; color:#f8fafc; margin-top:0; }
  .aviso { color:#fbbf24; }
  ul { padding-left:1.2rem; } li { margin:.4rem 0; }
  .pie { color:#94a3b8; font-size:.85rem; margin-top:1.5rem; }
</style>
</head>
<body>
  <main>
    <h1>Esto fue una <span class="aviso">simulación de phishing</span></h1>
    <p>Nadie ha robado tus datos: esta página forma parte de una prueba de
       concienciación de seguridad de tu organización.</p>
    <p><strong>¿Qué pasó?</strong> Interactuaste con un correo o un QR de prueba
       diseñado para parecer legítimo.</p>
    <p><strong>Señales que conviene revisar la próxima vez:</strong></p>
    <ul>
      <li>Revisa el remitente y el dominio real de los enlaces antes de hacer clic.</li>
      <li>Desconfía de la urgencia y de las peticiones de credenciales o datos sensibles.</li>
      <li>Verifica por otro canal cualquier mensaje inesperado que pida acción inmediata.</li>
    </ul>
    <p class="pie">Scytal — concienciación en seguridad de la información.</p>
  </main>
</body>
</html>
"""

async def _limitar(request: Request) -> None:
    """Rate limit 60/min por IP (§6.2). Falla abierto si Redis no está disponible."""
    ip = request.client.host if request.client else "anonima"
    if not await check_limit(f"rl:track:{ip}", limit=LIMITE_POR_IP, window_seconds=VENTANA_SEG):
        raise HTTPException(
            status_code=429,
            detail=error_payload("RATE_LIMITED", "Demasiadas solicitudes; espera un minuto.").model_dump(),
            headers=RETRY_AFTER,
        )

async def _validar(db: AsyncSession, t: str | None) -> tuple[str, object] | None:
    """→ ("destinatario", fila) | ("qr", zona) | None.

    Hash SHA-256 contra token_hash + vigencia de expira_en. Un token vencido y uno
    inexistente devuelven lo mismo (None): jamás se distingue si llegó a existir.
    """
    if not t:
        return None
    h = campana_repo.hash_token(t)
    ahora = datetime.now(timezone.utc)
    fila = (await db.execute(select(DestinatarioCampana).where(DestinatarioCampana.token_hash == h))).scalar_one_or_none()
    if fila is not None and fila.expira_en > ahora:
        return "destinatario", fila
    zona = (await db.execute(select(CampanaQrZona).where(CampanaQrZona.token_hash == h))).scalar_one_or_none()
    if zona is not None and zona.expira_en is not None and zona.expira_en > ahora:
        return "qr", zona
    return None

def _ip_de(request: Request) -> str | None:
    return request.client.host if request.client else None

def _awareness_url(t: str | None) -> str:
    return f"/track/awareness?t={t}" if t else "/track/awareness"

def insertar_token_action(html: str, token: str) -> str:
    """Reescribe el action del form para que el POST vuelva a /track con el token.

    El clonador guardó `action="/track/submit"` (marcador ACCION_FORM); aquí se le
    añade `?t={token}` SOLO en memoria — el HTML en BD nunca se toca.
    """
    return (
        html
        .replace(f'action="{ACCION_FORM}"', f'action="{ACCION_FORM}?t={token}"')
        .replace(f"action='{ACCION_FORM}'", f"action='{ACCION_FORM}?t={token}'")
    )

async def _landing_de(db: AsyncSession, campana_id, token: str) -> str | None:
    """landing_html de la plantilla de la campaña, con el action reescrito."""
    html = (await db.execute(
        select(Plantilla.landing_html)
        .join(Campana, Campana.plantilla_id == Plantilla.id_plantillas)
        .where(Campana.id_campanas == campana_id)
    )).scalar_one_or_none()
    if html is None:
        return None
    return insertar_token_action(html, token)

@router.get("/open")
async def abrir_pixel(request: Request, t: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    """Pixel 1x1: registra `abierto` + estampa abierto_en. Token inválido → igual el pixel."""
    await _limitar(request)
    v = await _validar(db, t)
    if v is not None and v[0] == "destinatario":
        fila = v[1]
        await campana_repo.marcar_abierto(db, fila.id_destinatarios_campana)
        await tracking_repo.registrar_evento(
            db, fila.id_destinatarios_campana, "abierto",
            canal_origen="correo", direccion_ip=_ip_de(request),
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
    return Response(content=PIXEL_1X1, media_type="image/gif", headers={"Cache-Control": "no-store"})

@router.get("/click")
async def clicar(request: Request, t: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    """Registra `click` y redirige a la landing. Inválido/vencido → awareness (genérico)."""
    await _limitar(request)
    v = await _validar(db, t)
    if v is None:
        return RedirectResponse(url=_awareness_url(t), status_code=302)
    tipo, obj = v
    if tipo == "destinatario":
        await campana_repo.marcar_clic(db, obj.id_destinatarios_campana)
        await tracking_repo.registrar_evento(
            db, obj.id_destinatarios_campana, "click",
            canal_origen="correo", direccion_ip=_ip_de(request),
            user_agent=request.headers.get("user-agent"),
        )
    else:
        await qr_repo.marcar_clic(db, obj)  
    await db.commit()
    return RedirectResponse(url=f"/track/landing?t={t}", status_code=302)

@router.get("/landing")
async def ver_landing(request: Request, t: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    """Landing de la campaña con el form reescrito a `/track/submit?t={token}`."""
    await _limitar(request)
    v = await _validar(db, t)
    if v is None:
        return RedirectResponse(url=_awareness_url(t), status_code=302)
    html = await _landing_de(db, v[1].campana_id, t)
    if html is None:
        return RedirectResponse(url=_awareness_url(t), status_code=302)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})

@router.post("/submit")
async def enviar_formulario(request: Request, t: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    """Registra `subido` y redirige al awareness.

    SIN modelo Pydantic de body: los campos del formulario falso (password, etc.)
    jamás se leen ni se guardan (§7). El canal QR anónimo no tiene fila a la que
    atribuir el evento → solo sirve el awareness.
    """
    await _limitar(request)
    v = await _validar(db, t)
    if v is not None and v[0] == "destinatario":
        fila = v[1]
        await tracking_repo.registrar_evento(
            db, fila.id_destinatarios_campana, "subido",
            canal_origen="correo", direccion_ip=_ip_de(request),
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
    return RedirectResponse(url=_awareness_url(t), status_code=303)

@router.get("/awareness")
async def awareness(request: Request, t: str | None = Query(default=None)):
    """Página educativa post-envío. `t` se acepta por spec (§4.9) pero NO se valida:
    la respuesta es SIEMPRE la misma (sin métricas, sin enumeración)."""
    await _limitar(request)
    return HTMLResponse(AWARENESS_HTML, headers={"Cache-Control": "no-store"})
