import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.usuario import Usuario
from app.repositories import destinatario_repository as destinatario_repo
from app.repositories import grupo_repository as grupo_repo
from app.repositories import maturity_repository as maturity_repo
from app.schemas.auth import error_payload
from app.schemas.maturity import HistorialItem, HistorialResponse, ResumenResponse, TrendItem, TrendResponse

router = APIRouter(prefix="/maturity", tags=["maturity"])

def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())

@router.get("/recipients/{destinatario_id}/history", response_model=HistorialResponse)
async def recipient_history(
    destinatario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Histórico del índice de phishing de un destinatario (§4.10)."""
    if not await maturity_repo.existe_destinatario(db, org_id, destinatario_id):
        _raise("NOT_FOUND", "Destinatario no encontrado", 404)
    filas = await destinatario_repo.historico_instantaneas(db, org_id, destinatario_id, limit)
    items = [
        HistorialItem(
            campana_id=f.campana_id,
            puntaje_phishing=float(f.puntaje_phishing),
            nivel=f.nivel,
            creado_en=f.creado_en,
        )
        for f in filas
    ]
    return HistorialResponse(destinatario_id=destinatario_id, items=items)

@router.get("/groups/{grupo_id}/trend", response_model=TrendResponse)
async def group_trend(
    grupo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Tendencia del índice promedio del grupo por campaña finalizada (§4.10)."""
    if await grupo_repo.find_by_id_in_org(db, grupo_id, org_id) is None:
        _raise("NOT_FOUND", "Grupo no encontrado", 404)
    filas = await maturity_repo.trend_grupo(db, org_id, grupo_id)
    items = [
        TrendItem(
            campana_id=f["campana_id"],
            nombre=f["nombre"],
            finalizada_en=f["finalizada_en"],
            promedio=f["promedio"],
            n_destinatarios=f["n_destinatarios"],
        )
        for f in filas
    ]
    return TrendResponse(grupo_id=grupo_id, items=items)

@router.get("/organization/summary", response_model=ResumenResponse)
async def organization_summary(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Resumen general para el dashboard principal (§4.10)."""
    return ResumenResponse(**await maturity_repo.resumen_organizacion(db, org_id))
