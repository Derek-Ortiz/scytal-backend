"""Repositorio de zonas QR (canal anónimo, decisión de diseño).

El token_qr va en claro en BD porque la imagen del QR se regenera bajo demanda y el propio
póster lo exhibe públicamente; el token_hash (SHA-256) es el que valida /track (Fase 4).
"""
import hashlib
import secrets
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qr_zona import CampanaQrZona


def _nueva_zona(campana_id: uuid.UUID, zona: str) -> CampanaQrZona:
    token = secrets.token_hex(32)
    return CampanaQrZona(
        campana_id=campana_id, zona=zona.strip(),
        token_qr=token, token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )


async def replace_zonas(db: AsyncSession, campana_id: uuid.UUID, zonas: list[str]) -> list[CampanaQrZona]:
    """Reemplaza el set de zonas (solo en `pendiente`): regenera tokens sin histórico que perder."""
    await db.execute(delete(CampanaQrZona).where(CampanaQrZona.campana_id == campana_id))
    filas = [_nueva_zona(campana_id, z) for z in zonas]
    db.add_all(filas)
    await db.flush()
    return filas


async def borrar_zonas(db: AsyncSession, campana_id: uuid.UUID) -> None:
    """Si el canal qr se retira de la lista de canales, sus zonas dejan de tener sentido."""
    await db.execute(delete(CampanaQrZona).where(CampanaQrZona.campana_id == campana_id))


async def get_zonas(db: AsyncSession, campana_id: uuid.UUID) -> list[CampanaQrZona]:
    res = await db.execute(
        select(CampanaQrZona).where(CampanaQrZona.campana_id == campana_id).order_by(CampanaQrZona.creado_en.asc())
    )
    return list(res.scalars().all())


async def find_by_token_hash(db: AsyncSession, token_hash: str) -> CampanaQrZona | None:
    """Validación en /track para el token de zona QR (Fase 4)."""
    res = await db.execute(select(CampanaQrZona).where(CampanaQrZona.token_hash == token_hash))
    return res.scalar_one_or_none()


async def marcar_clic(db: AsyncSession, zona: CampanaQrZona) -> CampanaQrZona:
    """Primer escaneo estampa clic_en; los siguientes no lo mueven (misma mecánica que tokens)."""
    if zona.clic_en is None:
        await db.execute(
            update(CampanaQrZona)
            .where(CampanaQrZona.id_campanas_qr_zonas == zona.id_campanas_qr_zonas)
            .values(clic_en=func.now())
        )
    return zona
