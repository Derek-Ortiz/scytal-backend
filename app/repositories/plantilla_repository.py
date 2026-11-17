"""Repositorio de plantillas (§4.7). Visibilidad: global (org_id NULL) + propias de la org."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campana import Campana
from app.models.plantilla import Plantilla

ESTADOS_QUE_BLOQUEAN = ("pendiente", "programada", "activa")


async def create(
    db: AsyncSession, org_id: uuid.UUID | None, nombre: str, perfil: str, canal: str,
    asunto: str | None, contenido_html: str, landing_html: str,
) -> Plantilla:
    p = Plantilla(
        org_id=org_id, nombre=nombre.strip(), perfil=perfil.strip(), canal=canal,
        asunto=(asunto.strip() if asunto else None),
        contenido_html=contenido_html, landing_html=landing_html,
    )
    db.add(p)
    await db.flush()
    return p


async def find_by_id_visible(db: AsyncSession, plantilla_id: uuid.UUID, org_id: uuid.UUID) -> Plantilla | None:
    """Visible si es global (org_id NULL) o de la propia organización (§6.1)."""
    res = await db.execute(
        select(Plantilla).where(
            Plantilla.id_plantillas == plantilla_id,
            (Plantilla.org_id.is_(None)) | (Plantilla.org_id == org_id),
        )
    )
    return res.scalar_one_or_none()


async def find_own(db: AsyncSession, plantilla_id: uuid.UUID, org_id: uuid.UUID) -> Plantilla | None:
    res = await db.execute(
        select(Plantilla).where(Plantilla.id_plantillas == plantilla_id, Plantilla.org_id == org_id)
    )
    return res.scalar_one_or_none()


async def list_visible(
    db: AsyncSession, org_id: uuid.UUID, limit: int, offset: int,
    perfil: str | None = None, canal: str | None = None,
) -> tuple[int, list[Plantilla]]:
    base = select(Plantilla).where((Plantilla.org_id.is_(None)) | (Plantilla.org_id == org_id))
    if perfil is not None:
        base = base.where(func.lower(Plantilla.perfil) == perfil.strip().lower())
    if canal is not None:
        base = base.where(Plantilla.canal == canal)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    res = await db.execute(base.order_by(Plantilla.creado_en.asc(), Plantilla.id_plantillas).limit(limit).offset(offset))
    return total, list(res.scalars().all())


async def update(db: AsyncSession, plantilla: Plantilla, **campos) -> Plantilla:
    for k, v in campos.items():
        if v is not None:
            setattr(plantilla, k, v.strip() if isinstance(v, str) else v)
    # asunto puede volver a None explícitamente solo si el canal cambia; aquí None = "no tocar"
    await db.flush()
    return plantilla


async def delete(db: AsyncSession, plantilla: Plantilla) -> None:
    await db.delete(plantilla)
    await db.flush()


async def en_uso(db: AsyncSession, plantilla_id: uuid.UUID) -> bool:
    """En uso = referenciada por una campaña que aún puede lanzarse (pendiente/programada/activa).

    DELETE solo si no está en uso (§4.7). Campañas viejas (completada/cancelada) la sueltan
    con ON DELETE SET NULL — la FK de campanas.plantilla_id.
    """
    res = await db.execute(
        select(func.count()).select_from(Campana).where(
            Campana.plantilla_id == plantilla_id,
            Campana.estado.in_(ESTADOS_QUE_BLOQUEAN),
        )
    )
    return res.scalar_one() > 0
