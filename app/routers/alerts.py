import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.usuario import Usuario
from app.repositories import alerta_repository as alerta_repo
from app.repositories import usuario_repository as user_repo
from app.schemas.alerta import AlertaListResponse, AlertaResponse
from app.schemas.auth import error_payload

router = APIRouter(prefix="/alerts", tags=["alerts"])

def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())

def _to_response(a) -> AlertaResponse:
    return AlertaResponse(
        id_alertas=a.id_alertas,
        tipo=a.tipo,
        referencia_tipo=a.referencia_tipo,
        referencia_id=a.referencia_id,
        resuelto=a.resuelto,
        resuelto_en=a.resuelto_en,
        creado_en=a.creado_en,
    )

@router.get("", response_model=AlertaListResponse)
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    tipo: str | None = Query(default=None, max_length=100),
    resuelto: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Alertas de la organización (§4.11), filtrables por tipo y estado."""
    total, items = await alerta_repo.list_by_org(db, org_id, limit, offset, tipo=tipo, resuelto=resuelto)
    return AlertaListResponse(total=total, items=[_to_response(a) for a in items], limit=limit, offset=offset)

@router.patch("/{alerta_id}/resolve", response_model=AlertaResponse)
async def resolve_alert(
    alerta_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Marca la alerta como resuelta (solo admin). La resolución queda en auditoría (§6.6)."""
    alerta = await alerta_repo.find_by_id_in_org(db, alerta_id, org_id)
    if alerta is None:
        _raise("NOT_FOUND", "Alerta no encontrada", 404)
    if alerta.resuelto:
        _raise("CONFLICT", "La alerta ya estaba resuelta", 409)
    await alerta_repo.marcar_resuelta(db, alerta)
    await user_repo.save_audit(
        db, org_id, "alert_resolved", f"Alerta resuelta: {alerta.tipo} ({alerta.id_alertas})", actor_id=actor.id_usuarios
    )
    await db.commit()
    return _to_response(alerta)
