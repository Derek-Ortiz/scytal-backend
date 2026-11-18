"""GET /previsualizar/{token} — sirve la landing congelada EXACTAMENTE como la verá el destinatario.

Público pero con JWT efímero (tipo='previsualizacion', 30 min) que SOLO se obtiene desde
`GET /templates/{id}/previsualizar` con sesión válida de la organización dueña. El HTML
servido ya viene domesticado (sin scripts) y autocontenido (CSS inline), así que la CSP
puede permitir estilos inline + imágenes/fuentes https: y NADA de JavaScript.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.repositories import plantilla_repository as plantilla_repo

router = APIRouter(prefix="/previsualizar", tags=["previsualizacion"])

MINUTOS_ENLACE_PREVIA = 30


@router.get("/{token}", response_class=HTMLResponse)
async def ver_landing(token: str, db: AsyncSession = Depends(get_db)):
    """Landing del snapshot para el destinatario (sin tracking aún: Fase 4 reusa esto)."""
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status_code=404, detail="Enlace de previsualización inválido o expirado")
    if claims.get("tipo") != "previsualizacion" or not claims.get("sub") or not claims.get("org_id"):
        raise HTTPException(status_code=404, detail="Enlace de previsualización inválido o expirado")
    try:
        plantilla_id = uuid.UUID(str(claims["sub"]))
        org_id = uuid.UUID(str(claims["org_id"]))
    except ValueError:
        raise HTTPException(status_code=404, detail="Enlace de previsualización inválido o expirado")
    # find_by_id_visible aplica §6.1: la plantilla debe existir y ser visible para la org del token
    p = await plantilla_repo.find_by_id_visible(db, plantilla_id, org_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    return HTMLResponse(
        p.landing_html,
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )
