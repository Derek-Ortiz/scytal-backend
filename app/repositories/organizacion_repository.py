import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campana import Campana
from app.models.destinatario import Destinatario
from app.models.grupo import Grupo
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario


def slugify(nombre: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", nombre.strip().lower())
    return s.strip("-") or "org"


async def find_by_slug(db: AsyncSession, slug: str) -> Organizacion | None:
    res = await db.execute(select(Organizacion).where(Organizacion.slug == slug))
    return res.scalar_one_or_none()


async def find_by_id(db: AsyncSession, oid: uuid.UUID) -> Organizacion | None:
    res = await db.execute(select(Organizacion).where(Organizacion.id_organizaciones == oid))
    return res.scalar_one_or_none()


async def create(db: AsyncSession, nombre: str, slug: str | None = None) -> Organizacion:
    final_slug = slug if slug else slugify(nombre)
    org = Organizacion(nombre=nombre.strip(), slug=final_slug)
    db.add(org)
    await db.flush()
    return org


async def update(db: AsyncSession, org: Organizacion, nombre: str | None = None, slug: str | None = None) -> Organizacion:
    if nombre is not None:
        org.nombre = nombre.strip()
    if slug is not None:
        org.slug = slug
    await db.flush()
    return org


async def list_all(db: AsyncSession, limit: int, offset: int) -> tuple[int, list[Organizacion]]:
    """Todas las organizaciones (solo admin_plataforma)."""
    total = (await db.execute(select(func.count()).select_from(Organizacion))).scalar_one()
    res = await db.execute(select(Organizacion).order_by(Organizacion.creado_en.desc()).limit(limit).offset(offset))
    return total, list(res.scalars().all())


async def metricas(db: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    """Conteos para el detalle/listado de organizaciones (decisión #7)."""
    usuarios_activos = (
        await db.execute(select(func.count()).select_from(Usuario).where(Usuario.org_id == org_id, Usuario.activo.is_(True)))
    ).scalar_one()
    grupos_n = (await db.execute(select(func.count()).select_from(Grupo).where(Grupo.org_id == org_id))).scalar_one()
    destinatarios_activos = (
        await db.execute(
            select(func.count()).select_from(Destinatario).where(Destinatario.org_id == org_id, Destinatario.activo.is_(True))
        )
    ).scalar_one()
    campanas_totales = (
        await db.execute(select(func.count()).select_from(Campana).where(Campana.org_id == org_id))
    ).scalar_one()
    campanas_activas = (
        await db.execute(
            select(func.count()).select_from(Campana).where(Campana.org_id == org_id, Campana.estado == "activa")
        )
    ).scalar_one()
    return {
        "usuarios_activos": usuarios_activos,
        "grupos": grupos_n,
        "destinatarios_activos": destinatarios_activos,
        "campanas_totales": campanas_totales,
        "campanas_activas": campanas_activas,
    }
