import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campana import Campana
from app.models.destinatario import Destinatario
from app.models.grupo import Grupo


async def create(db: AsyncSession, org_id: uuid.UUID, nombre: str, perfil: str) -> Grupo:
    grupo = Grupo(org_id=org_id, nombre=nombre.strip(), perfil=perfil.strip())
    db.add(grupo)
    await db.flush()
    return grupo


async def find_by_id_in_org(db: AsyncSession, grupo_id: uuid.UUID, org_id: uuid.UUID) -> Grupo | None:
    """Búsqueda siempre acotada a la organización del actor (§6.1)."""
    res = await db.execute(select(Grupo).where(Grupo.id_grupos == grupo_id, Grupo.org_id == org_id))
    return res.scalar_one_or_none()


async def find_by_nombre(db: AsyncSession, org_id: uuid.UUID, nombre: str) -> Grupo | None:
    res = await db.execute(select(Grupo).where(Grupo.org_id == org_id, func.lower(Grupo.nombre) == nombre.strip().lower()))
    return res.scalar_one_or_none()


async def list_by_org(db: AsyncSession, org_id: uuid.UUID, limit: int, offset: int) -> tuple[int, list[Grupo]]:
    total = (await db.execute(select(func.count()).select_from(Grupo).where(Grupo.org_id == org_id))).scalar_one()
    res = await db.execute(select(Grupo).where(Grupo.org_id == org_id).order_by(Grupo.creado_en.asc()).limit(limit).offset(offset))
    return total, list(res.scalars().all())


async def update(db: AsyncSession, grupo: Grupo, nombre: str | None = None, perfil: str | None = None) -> Grupo:
    if nombre is not None:
        grupo.nombre = nombre.strip()
    if perfil is not None:
        grupo.perfil = perfil.strip()
    await db.flush()
    return grupo


async def delete(db: AsyncSession, grupo: Grupo) -> None:
    await db.delete(grupo)
    await db.flush()


async def has_campanas(db: AsyncSession, grupo_id: uuid.UUID) -> bool:
    """DELETE solo si no hay campañas asociadas (RESTRICT del esquema)."""
    res = await db.execute(select(func.count()).select_from(Campana).where(Campana.grupo_id == grupo_id))
    return res.scalar_one() > 0


async def count_destinatarios_activos(db: AsyncSession, grupo_id: uuid.UUID) -> int:
    res = await db.execute(
        select(func.count()).select_from(Destinatario).where(Destinatario.grupo_id == grupo_id, Destinatario.activo.is_(True))
    )
    return res.scalar_one()


async def indice_promedio(db: AsyncSession, org_id: uuid.UUID, grupo_id: uuid.UUID) -> float | None:
    """Promedio del ÚLTIMO puntaje por destinatario activo del grupo. None si nadie tiene datos."""
    query = text("""
        SELECT AVG(p.puntaje) FROM (
            SELECT DISTINCT ON (ip.destinatario_id) ip.puntaje_phishing AS puntaje
            FROM instantaneas_phishing ip
            JOIN destinatarios d ON d.id_destinatarios = ip.destinatario_id
            WHERE ip.org_id = :org_id
              AND d.grupo_id = :grupo_id
              AND d.activo IS TRUE
            ORDER BY ip.destinatario_id, ip.creado_en DESC
        ) p
    """)
    res = await db.execute(query, {"org_id": str(org_id), "grupo_id": str(grupo_id)})
    valor = res.scalar_one()
    return float(valor) if valor is not None else None


async def grupos_con_informe(db: AsyncSession, org_id: uuid.UUID) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, float]]:
    """En un solo viaje: destinatarios activos por grupo y el índice promedio del grupo.

    Índice promedio = promedio del último puntaje por destinatario activo del grupo.
    Retorna ({grupo_id: n_destinatarios}, {grupo_id: promedio}).
    """
    # Conteo por grupo
    res = await db.execute(
        select(Destinatario.grupo_id, func.count())
        .where(Destinatario.org_id == org_id, Destinatario.activo.is_(True))
        .group_by(Destinatario.grupo_id)
    )
    conteos = {gid: n for gid, n in res.all()}

    # Último puntaje por destinatario → promedio por grupo
    q = text("""
        SELECT d.grupo_id, AVG(p.puntaje) AS promedio
        FROM (
            SELECT DISTINCT ON (ip.destinatario_id) ip.destinatario_id, ip.puntaje_phishing AS puntaje
            FROM instantaneas_phishing ip
            WHERE ip.org_id = :org_id
            ORDER BY ip.destinatario_id, ip.creado_en DESC
        ) p
        JOIN destinatarios d ON d.id_destinatarios = p.destinatario_id
        WHERE d.org_id = :org_id AND d.activo IS TRUE
        GROUP BY d.grupo_id
    """)
    res2 = await db.execute(q, {"org_id": str(org_id)})
    promedios = {gid: float(avg) for gid, avg in res2.all()}
    return conteos, promedios
