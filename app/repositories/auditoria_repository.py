import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auditoria import EventoAuditoria
from app.models.usuario import Usuario

async def listar(
    db: AsyncSession,
    org_id: uuid.UUID,
    limit: int,
    offset: int,
    tipo: str | None = None,
    actor_id: uuid.UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> tuple[int, list[tuple[EventoAuditoria, str | None]]]:
    """Bitácora de la organización (§6.1): SIEMPRE filtrada por org_id del JWT, con actor resuelto."""
    filtros = [EventoAuditoria.org_id == org_id]
    if tipo is not None:
        filtros.append(EventoAuditoria.tipo == tipo)
    if actor_id is not None:
        filtros.append(EventoAuditoria.actor_id == actor_id)
    if desde is not None:
        filtros.append(EventoAuditoria.creado_en >= desde)
    if hasta is not None:
        filtros.append(EventoAuditoria.creado_en <= hasta)

    total = (await db.execute(
        select(func.count()).select_from(EventoAuditoria).where(*filtros)
    )).scalar_one()
    res = await db.execute(
        select(EventoAuditoria, Usuario.correo)
        .outerjoin(Usuario, Usuario.id_usuarios == EventoAuditoria.actor_id)
        .where(*filtros)
        .order_by(EventoAuditoria.creado_en.desc(), EventoAuditoria.id_eventos_auditoria.desc())
        .limit(limit)
        .offset(offset)
    )
    return int(total), [(ev, str(correo) if correo is not None else None) for ev, correo in res.all()]
