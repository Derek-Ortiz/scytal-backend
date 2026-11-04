import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organizacion import Organizacion


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
