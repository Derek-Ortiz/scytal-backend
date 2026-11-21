import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campana import Campana
from app.models.destinatario import Destinatario
from app.models.instantanea import InstantaneaPhishing

async def existe_destinatario(db: AsyncSession, org_id: uuid.UUID, destinatario_id: uuid.UUID) -> bool:
    res = await db.execute(
        select(Destinatario.id_destinatarios)
        .where(Destinatario.id_destinatarios == destinatario_id, Destinatario.org_id == org_id)
    )
    return res.scalar_one_or_none() is not None

async def trend_grupo(db: AsyncSession, org_id: uuid.UUID, grupo_id: uuid.UUID) -> list[dict]:
    """Promedio del grupo por campaña finalizada, en orden cronológico (§4.10)."""
    query = text("""
        SELECT c.id_campanas AS campana_id, c.nombre, c.finalizada_en,
               AVG(ip.puntaje_phishing) AS promedio, COUNT(*) AS n_destinatarios
        FROM instantaneas_phishing ip
        JOIN destinatarios d ON d.id_destinatarios = ip.destinatario_id
        JOIN campanas c ON c.id_campanas = ip.campana_id
        WHERE ip.org_id = :org_id AND d.grupo_id = :grupo_id
        GROUP BY c.id_campanas, c.nombre, c.finalizada_en, c.creado_en
        ORDER BY c.creado_en ASC
    """)
    res = await db.execute(query, {"org_id": str(org_id), "grupo_id": str(grupo_id)})
    return [
        {
            "campana_id": r["campana_id"],
            "nombre": r["nombre"],
            "finalizada_en": r["finalizada_en"],
            "promedio": float(r["promedio"]),
            "n_destinatarios": int(r["n_destinatarios"]),
        }
        for r in res.mappings()
    ]

QUERY_RESUMEN = text("""
    WITH ultimo AS (
        SELECT DISTINCT ON (ip.destinatario_id) ip.destinatario_id, ip.puntaje_phishing, ip.nivel
        FROM instantaneas_phishing ip
        WHERE ip.org_id = :org_id
        ORDER BY ip.destinatario_id, ip.creado_en DESC
    )
    SELECT
        (SELECT COUNT(*) FROM destinatarios WHERE org_id = :org_id AND activo IS TRUE) AS activos,
        (SELECT AVG(puntaje_phishing) FROM ultimo u
         JOIN destinatarios d ON d.id_destinatarios = u.destinatario_id
         WHERE d.activo IS TRUE) AS indice,
        (SELECT COUNT(*) FROM ultimo u
         JOIN destinatarios d ON d.id_destinatarios = u.destinatario_id
         WHERE d.activo IS TRUE AND u.nivel = 'bajo') AS n_bajo,
        (SELECT COUNT(*) FROM ultimo u
         JOIN destinatarios d ON d.id_destinatarios = u.destinatario_id
         WHERE d.activo IS TRUE AND u.nivel = 'medio') AS n_medio,
        (SELECT COUNT(*) FROM ultimo u
         JOIN destinatarios d ON d.id_destinatarios = u.destinatario_id
         WHERE d.activo IS TRUE AND u.nivel = 'alto') AS n_alto,
        (SELECT COUNT(*) FROM ultimo u
         JOIN destinatarios d ON d.id_destinatarios = u.destinatario_id
         WHERE d.activo IS TRUE AND u.nivel = 'critico') AS n_critico
""")

async def resumen_organizacion(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Dashboard §4.10: activos, índice promedio y distribución por nivel del último puntaje."""
    fila = (await db.execute(QUERY_RESUMEN, {"org_id": str(org_id)})).mappings().one()
    campanas = (await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(Campana.estado == "completada").label("completadas"),
            func.max(Campana.finalizada_en).label("ultima_finalizacion"),
        ).where(Campana.org_id == org_id)
    )).one()
    return {
        "destinatarios_activos": int(fila["activos"]),
        "indice_promedio": float(fila["indice"]) if fila["indice"] is not None else None,
        "distribucion": {
            "bajo": int(fila["n_bajo"]),
            "medio": int(fila["n_medio"]),
            "alto": int(fila["n_alto"]),
            "critico": int(fila["n_critico"]),
        },
        "campanas": {
            "total": int(campanas.total),
            "completadas": int(campanas.completadas),
        },
        "ultima_finalizacion": campanas.ultima_finalizacion,
    }
