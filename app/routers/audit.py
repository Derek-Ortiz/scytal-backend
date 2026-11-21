import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.usuario import Usuario
from app.repositories import auditoria_repository as auditoria_repo
from app.schemas.auditoria import AuditoriaListResponse, AuditoriaResponse

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("", response_model=AuditoriaListResponse)
async def list_audit(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    tipo: str | None = Query(default=None, max_length=100),
    actor_id: uuid.UUID | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Bitácora paginada de la organización (§4.12) con filtros por tipo, actor y rango de fechas."""
    total, filas = await auditoria_repo.listar(
        db, org_id, limit, offset, tipo=tipo, actor_id=actor_id, desde=desde, hasta=hasta
    )
    items = [
        AuditoriaResponse(
            id_eventos_auditoria=ev.id_eventos_auditoria,
            tipo=ev.tipo,
            actor_id=ev.actor_id,
            actor_tipo=ev.actor_tipo,
            actor_correo=correo,
            detalle=ev.detalle,
            creado_en=ev.creado_en,
        )
        for ev, correo in filas
    ]
    return AuditoriaListResponse(total=total, items=items, limit=limit, offset=offset)
