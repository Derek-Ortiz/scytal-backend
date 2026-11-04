import uuid
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auditoria import EventoAuditoria
from app.models.historial import HistorialContrasenas
from app.models.usuario import Usuario


async def find_by_email(db: AsyncSession, correo: str) -> Usuario | None:
    res = await db.execute(select(Usuario).where(Usuario.correo == correo.lower().strip()))
    return res.scalar_one_or_none()


async def find_by_id(db: AsyncSession, uid: uuid.UUID) -> Usuario | None:
    res = await db.execute(select(Usuario).where(Usuario.id_usuarios == uid))
    return res.scalar_one_or_none()


async def add_user(db: AsyncSession, user: Usuario) -> Usuario:
    db.add(user)
    await db.flush()
    return user


async def add_history(db: AsyncSession, usuario_id: uuid.UUID, hash_contrasena: str) -> HistorialContrasenas:
    h = HistorialContrasenas(usuario_id=usuario_id, hash_contrasena=hash_contrasena)
    db.add(h)
    await db.flush()
    return h


async def last_hashes(db: AsyncSession, usuario_id: uuid.UUID, limit: int = 3) -> list[str]:
    res = await db.execute(
        select(HistorialContrasenas.hash_contrasena)
        .where(HistorialContrasenas.usuario_id == usuario_id)
        .order_by(HistorialContrasenas.creado_en.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def save_audit(db: AsyncSession, org_id: uuid.UUID | None, tipo: str, detalle: str, actor_id: uuid.UUID | None = None) -> None:
    """Opción B: solo audita si hay org_id. Si no, se registra en log estructurado."""
    if org_id is None:
        return
    ev = EventoAuditoria(org_id=org_id, tipo=tipo, actor_id=actor_id, detalle=detalle)
    db.add(ev)
    # flush lo hace el llamador (commit al final)
