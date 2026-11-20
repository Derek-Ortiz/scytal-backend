import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.destinatario import Destinatario
from app.models.grupo import Grupo
from app.models.instantanea import InstantaneaPhishing

async def create(db: AsyncSession, org_id: uuid.UUID, grupo_id: uuid.UUID, correo: str) -> Destinatario:
    """correo va normalizado en minúsculas (la columna es CITEXT: unicidad case-insensitive)."""
    d = Destinatario(org_id=org_id, grupo_id=grupo_id, correo=correo.strip().lower())
    db.add(d)
    await db.flush()
    return d

async def find_by_id_in_org(db: AsyncSession, destinatario_id: uuid.UUID, org_id: uuid.UUID) -> Destinatario | None:
    """Búsqueda siempre acotada a la organización del actor (§6.1)."""
    res = await db.execute(
        select(Destinatario).where(Destinatario.id_destinatarios == destinatario_id, Destinatario.org_id == org_id)
    )
    return res.scalar_one_or_none()

async def find_by_correo(db: AsyncSession, org_id: uuid.UUID, correo: str) -> Destinatario | None:
    """CITEXT compara sin distinguir mayúsculas: cubre todos los casos de uk_destinatarios_org_correo."""
    res = await db.execute(
        select(Destinatario).where(Destinatario.org_id == org_id, Destinatario.correo == correo.strip().lower())
    )
    return res.scalar_one_or_none()

async def list_by_org(
    db: AsyncSession, org_id: uuid.UUID, limit: int, offset: int, grupo_id: uuid.UUID | None = None
) -> tuple[int, list[Destinatario]]:
    """Listado de la org con filtro opcional por grupo (§4.6)."""
    base = select(Destinatario).where(Destinatario.org_id == org_id)
    if grupo_id is not None:
        base = base.where(Destinatario.grupo_id == grupo_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    res = await db.execute(base.order_by(Destinatario.creado_en.asc()).limit(limit).offset(offset))
    return total, list(res.scalars().all())

async def update(
    db: AsyncSession, destinatario: Destinatario, correo: str | None = None, grupo_id: uuid.UUID | None = None
) -> Destinatario:
    if correo is not None:
        destinatario.correo = correo.strip().lower()
    if grupo_id is not None:
        destinatario.grupo_id = grupo_id
    await db.flush()
    return destinatario

async def set_activo(db: AsyncSession, destinatario: Destinatario, activo: bool) -> Destinatario:
    """Borrado lógico (decisión #9): conserva el registro y su histórico."""
    destinatario.activo = activo
    await db.flush()
    return destinatario

async def correos_existentes(db: AsyncSession, org_id: uuid.UUID, correos: list[str]) -> set[str]:
    """De la lista dada, cuáles ya existen en la org (activos o no). Para el dedupe del CSV."""
    if not correos:
        return set()
    res = await db.execute(
        select(Destinatario.correo).where(
            Destinatario.org_id == org_id, Destinatario.correo.in_([c.lower() for c in correos])
        )
    )
    return {str(c) for c in res.scalars().all()}

async def historico_instantaneas(
    db: AsyncSession, org_id: uuid.UUID, destinatario_id: uuid.UUID, limit: int = 20
) -> list[InstantaneaPhishing]:
    """Histórico del índice de phishing del destinatario (más reciente primero)."""
    res = await db.execute(
        select(InstantaneaPhishing)
        .where(InstantaneaPhishing.org_id == org_id, InstantaneaPhishing.destinatario_id == destinatario_id)
        .order_by(InstantaneaPhishing.creado_en.desc())
        .limit(limit)
    )
    return list(res.scalars().all())

async def count_activos(db: AsyncSession, org_id: uuid.UUID) -> int:
    res = await db.execute(
        select(func.count()).select_from(Destinatario).where(Destinatario.org_id == org_id, Destinatario.activo.is_(True))
    )
    return res.scalar_one()

async def grupos_por_nombre(db: AsyncSession, org_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """{nombre_minúsculas: id_grupos} de todos los grupos de la org — para el mapeo del CSV."""
    res = await db.execute(select(Grupo.id_grupos, Grupo.nombre).where(Grupo.org_id == org_id))
    return {str(nombre).strip().lower(): gid for gid, nombre in res.all()}
