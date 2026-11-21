import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerta import Alerta

async def list_by_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    limit: int,
    offset: int,
    tipo: str | None = None,
    resuelto: bool | None = None,
) -> tuple[int, list[Alerta]]:
    """Alertas de la organización (§6.1), filtrables por tipo y estado de resolución."""
    base = select(Alerta).where(Alerta.org_id == org_id)
    if tipo is not None:
        base = base.where(Alerta.tipo == tipo)
    if resuelto is not None:
        base = base.where(Alerta.resuelto.is_(resuelto))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    res = await db.execute(base.order_by(Alerta.creado_en.desc(), Alerta.id_alertas.desc()).limit(limit).offset(offset))
    return int(total), list(res.scalars().all())

async def find_by_id_in_org(db: AsyncSession, alerta_id: uuid.UUID, org_id: uuid.UUID) -> Alerta | None:
    res = await db.execute(select(Alerta).where(Alerta.id_alertas == alerta_id, Alerta.org_id == org_id))
    return res.scalar_one_or_none()

async def marcar_resuelta(db: AsyncSession, alerta: Alerta) -> Alerta:
    alerta.resuelto = True
    alerta.resuelto_en = datetime.now(timezone.utc)
    await db.flush()
    return alerta

async def count_pendientes(db: AsyncSession, org_id: uuid.UUID) -> int:
    res = await db.execute(
        select(func.count()).select_from(Alerta).where(Alerta.org_id == org_id, Alerta.resuelto.is_(False))
    )
    return res.scalar_one()
