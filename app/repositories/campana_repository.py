import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campana import Campana, CampanaCanal, DestinatarioCampana
from app.models.destinatario import Destinatario
from app.models.qr_zona import CampanaQrZona

def generar_token() -> str:
    """Token en claro de 256 bits (solo se muestra una vez al destinatario; en BD va el hash)."""
    return secrets.token_hex(32)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

async def create(
    db: AsyncSession, org_id: uuid.UUID, grupo_id: uuid.UUID, plantilla_id: uuid.UUID | None,
    nombre: str, expiracion_horas: int,
) -> Campana:
    c = Campana(
        org_id=org_id, grupo_id=grupo_id, plantilla_id=plantilla_id,
        nombre=nombre.strip(), estado="pendiente", expiracion_horas=expiracion_horas,
    )
    db.add(c)
    await db.flush()
    return c

async def find_by_id_in_org(db: AsyncSession, campana_id: uuid.UUID, org_id: uuid.UUID) -> Campana | None:
    """Búsqueda siempre acotada a la organización del actor (§6.1)."""
    res = await db.execute(
        select(Campana).where(Campana.id_campanas == campana_id, Campana.org_id == org_id)
    )
    return res.scalar_one_or_none()

async def list_by_org(
    db: AsyncSession, org_id: uuid.UUID, limit: int, offset: int,
    estado: str | None = None, grupo_id: uuid.UUID | None = None,
) -> tuple[int, list[Campana]]:
    base = select(Campana).where(Campana.org_id == org_id)
    if estado is not None:
        base = base.where(Campana.estado == estado)
    if grupo_id is not None:
        base = base.where(Campana.grupo_id == grupo_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    res = await db.execute(base.order_by(Campana.creado_en.desc(), Campana.id_campanas).limit(limit).offset(offset))
    return total, list(res.scalars().all())

async def update_campos(db: AsyncSession, campana: Campana, **campos) -> Campana:
    for k, v in campos.items():
        if v is not None:
            setattr(campana, k, v.strip() if isinstance(v, str) else v)
    await db.flush()
    return campana

async def set_estado(db: AsyncSession, campana: Campana, estado: str) -> Campana:
    campana.estado = estado
    await db.flush()
    return campana

async def replace_canales(db: AsyncSession, campana_id: uuid.UUID, canales: list[str]) -> None:
    await db.execute(delete(CampanaCanal).where(CampanaCanal.campana_id == campana_id))
    db.add_all([CampanaCanal(campana_id=campana_id, canal=c) for c in canales])
    await db.flush()

async def get_canales(db: AsyncSession, campana_id: uuid.UUID) -> list[str]:
    res = await db.execute(select(CampanaCanal.canal).where(CampanaCanal.campana_id == campana_id))
    return [str(c) for c in res.scalars().all()]

async def canales_de_campanas(
    db: AsyncSession, campana_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Canales de varias campañas en un solo viaje (para listar sin N+1)."""
    if not campana_ids:
        return {}
    res = await db.execute(select(CampanaCanal).where(CampanaCanal.campana_id.in_(campana_ids)))
    out: dict[uuid.UUID, list[str]] = {}
    for cc in res.scalars().all():
        out.setdefault(cc.campana_id, []).append(str(cc.canal))
    return out

async def zonas_de_campanas(
    db: AsyncSession, campana_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Nombres de zona QR de varias campañas en un solo viaje (para listar sin N+1)."""
    if not campana_ids:
        return {}
    res = await db.execute(
        select(CampanaQrZona.campana_id, CampanaQrZona.zona).where(CampanaQrZona.campana_id.in_(campana_ids))
    )
    out: dict[uuid.UUID, list[str]] = {}
    for cid, zona in res.all():
        out.setdefault(cid, []).append(str(zona))
    return out

async def destinatarios_activos_del_grupo(db: AsyncSession, grupo_id: uuid.UUID) -> list[Destinatario]:
    res = await db.execute(
        select(Destinatario).where(Destinatario.grupo_id == grupo_id, Destinatario.activo.is_(True))
    )
    return list(res.scalars().all())

async def preparar_tokens(
    db: AsyncSession, campana_id: uuid.UUID, destinatarios: list[Destinatario], expiracion_horas: int
) -> list[tuple[DestinatarioCampana, str]]:
    """(Re)genera tokens para los destinatarios activos del grupo. Retorna [(fila, token_claro)].

    - Fila nueva por cada destinatario sin token; la existente se REINICIA (nuevo token,
      contadores a None, nueva expiración) — relanzar siempre parte de cero.
    - Filas huérfanas (destinatario ya no activo en el grupo) quedan muertas: expira_en = ahora.
    """
    ahora = datetime.now(timezone.utc)
    expira = ahora + timedelta(hours=expiracion_horas)
    res = await db.execute(select(DestinatarioCampana).where(DestinatarioCampana.campana_id == campana_id))
    existentes = {row.destinatario_id: row for row in res.scalars().all()}

    vivos: set[uuid.UUID] = set()
    pares: list[tuple[DestinatarioCampana, str]] = []
    for d in destinatarios:
        vivos.add(d.id_destinatarios)
        token = generar_token()
        fila = existentes.get(d.id_destinatarios)
        if fila is None:
            fila = DestinatarioCampana(
                campana_id=campana_id, destinatario_id=d.id_destinatarios,
                token_hash=hash_token(token), expira_en=expira,
            )
            db.add(fila)
        else:
            fila.token_hash = hash_token(token)
            fila.expira_en = expira
            fila.abierto_en = None
            fila.clic_en = None
            fila.enviado_en = None
        pares.append((fila, token))

    for id_dest, fila in existentes.items():
        if id_dest not in vivos:
            fila.expira_en = ahora
    await db.flush()
    return pares

async def caducar_tokens(db: AsyncSession, campana_id: uuid.UUID) -> None:
    """Cancelación (decisión): los tokens mueren AL INSTANTE, no al final del día."""
    await db.execute(
        update(DestinatarioCampana)
        .where(DestinatarioCampana.campana_id == campana_id)
        .values(expira_en=datetime.now(timezone.utc))
    )

async def re_datuar_tokens(db: AsyncSession, campana_id: uuid.UUID, expiracion_horas: int) -> None:
    """PATCH de expiración con la campaña activa: revive también los ya vencidos (decisión)."""
    await db.execute(
        update(DestinatarioCampana)
        .where(DestinatarioCampana.campana_id == campana_id)
        .values(expira_en=datetime.now(timezone.utc) + timedelta(hours=expiracion_horas))
    )

async def marcar_abierto(db: AsyncSession, fila_id: uuid.UUID) -> None:
    """Primer pixel de apertura estampa abierto_en; los siguientes no lo mueven."""
    await db.execute(
        update(DestinatarioCampana)
        .where(DestinatarioCampana.id_destinatarios_campana == fila_id, DestinatarioCampana.abierto_en.is_(None))
        .values(abierto_en=func.now())
    )

async def marcar_clic(db: AsyncSession, fila_id: uuid.UUID) -> None:
    """Primer clic estampa clic_en; los siguientes no lo mueven (misma mecánica que el QR)."""
    await db.execute(
        update(DestinatarioCampana)
        .where(DestinatarioCampana.id_destinatarios_campana == fila_id, DestinatarioCampana.clic_en.is_(None))
        .values(clic_en=func.now())
    )

QUERY_EMBUDO = text("""
    SELECT
        COUNT(*) AS total,
        COUNT(enviado_en) AS enviados,
        COUNT(abierto_en) AS abiertos,
        COUNT(clic_en) AS clics,
        COUNT(*) FILTER (
            WHERE EXISTS (
                SELECT 1 FROM eventos_tracking et
                WHERE et.destinatario_campana_id = dc.id_destinatarios_campana
                  AND et.tipo = 'subido'
                  AND et.creado_en >= c.iniciada_en
            )
        ) AS subidos
    FROM destinatarios_campana dc
    JOIN campanas c ON c.id_campanas = dc.campana_id
    WHERE dc.campana_id = :cid
""")

async def stats_embudo(db: AsyncSession, campana_id: uuid.UUID) -> dict:
    """Embudo §4.8 (enviados/abiertos/clics/enviados-datos) + clics QR anónimos aparte.

    Los clics de zona QR NO entran al embudo: son anónimos, no se pueden atribuir a nadie.
    """
    fila = (await db.execute(QUERY_EMBUDO, {"cid": str(campana_id)})).mappings().one()
    qr = (await db.execute(
        select(func.count()).select_from(CampanaQrZona)
        .where(CampanaQrZona.campana_id == campana_id, CampanaQrZona.clic_en.is_not(None))
    )).scalar_one()
    return {
        "total": int(fila["total"]),
        "enviados": int(fila["enviados"]),
        "abiertos": int(fila["abiertos"]),
        "clics": int(fila["clics"]),
        "subidos": int(fila["subidos"]),
        "qr_clics": int(qr),
    }

QUERY_TABLA = text("""
    SELECT
        d.id_destinatarios AS destinatario_id,
        d.correo,
        dc.enviado_en,
        dc.abierto_en,
        dc.clic_en,
        dc.expira_en,
        EXISTS (
            SELECT 1 FROM eventos_tracking et
            WHERE et.destinatario_campana_id = dc.id_destinatarios_campana
              AND et.tipo = 'subido'
              AND et.creado_en >= c.iniciada_en
        ) AS subio,
        ip.puntaje_phishing,
        ip.nivel
    FROM destinatarios_campana dc
    JOIN campanas c ON c.id_campanas = dc.campana_id
    JOIN destinatarios d ON d.id_destinatarios = dc.destinatario_id
    LEFT JOIN LATERAL (
        SELECT ip.puntaje_phishing, ip.nivel
        FROM instantaneas_phishing ip
        WHERE ip.campana_id = dc.campana_id AND ip.destinatario_id = dc.destinatario_id
        ORDER BY ip.creado_en DESC
        LIMIT 1
    ) ip ON TRUE
    WHERE dc.campana_id = :cid
    ORDER BY d.correo
    LIMIT :limit OFFSET :offset
""")

async def tabla_destinatarios(
    db: AsyncSession, campana_id: uuid.UUID, limit: int, offset: int
) -> tuple[int, list[dict]]:
    """Tabla §4.8 por destinatario: estado de envío/interacción + índice de la última instantánea."""
    total = (await db.execute(
        select(func.count()).select_from(DestinatarioCampana).where(DestinatarioCampana.campana_id == campana_id)
    )).scalar_one()
    res = await db.execute(QUERY_TABLA, {"cid": str(campana_id), "limit": limit, "offset": offset})
    ahora = datetime.now(timezone.utc)
    filas = []
    for m in res.mappings():
        filas.append({
            "destinatario_id": m["destinatario_id"],
            "correo": str(m["correo"]),
            "enviado": m["enviado_en"] is not None,
            "abrio": m["abierto_en"] is not None,
            "clico": m["clic_en"] is not None,
            "subio": bool(m["subio"]),
            "expira_en": m["expira_en"],
            "vencido": m["expira_en"] is not None and m["expira_en"] <= ahora,
            "puntaje_phishing": float(m["puntaje_phishing"]) if m["puntaje_phishing"] is not None else None,
            "nivel": m["nivel"],
        })
    return int(total), filas

QUERY_FINALIZAR = text("""
    SELECT
        dc.id_destinatarios_campana,
        dc.destinatario_id,
        dc.abierto_en,
        dc.clic_en,
        EXISTS (
            SELECT 1 FROM eventos_tracking et
            WHERE et.destinatario_campana_id = dc.id_destinatarios_campana
              AND et.tipo = 'subido'
              AND et.creado_en >= c.iniciada_en
        ) AS envio
    FROM destinatarios_campana dc
    JOIN campanas c ON c.id_campanas = dc.campana_id
    WHERE dc.campana_id = :cid
""")

async def filas_para_finalizar(db: AsyncSession, campana_id: uuid.UUID) -> list[dict]:
    res = await db.execute(QUERY_FINALIZAR, {"cid": str(campana_id)})
    return [dict(m) for m in res.mappings()]

QUERY_FEEDBACK = text("""
    SELECT DISTINCT ON (ip.destinatario_id)
        d.correo, ip.puntaje_phishing, ip.nivel
    FROM instantaneas_phishing ip
    JOIN destinatarios d ON d.id_destinatarios = ip.destinatario_id
    WHERE ip.campana_id = :cid
    ORDER BY ip.destinatario_id, ip.creado_en DESC
""")

async def resultados_para_feedback(db: AsyncSession, campana_id: uuid.UUID) -> list[dict]:
    """Resultados (correo, puntaje, nivel) del ÚLTIMO cierre de la campaña, para el feedback."""
    res = await db.execute(QUERY_FEEDBACK, {"cid": str(campana_id)})
    return [
        {"correo": str(m["correo"]), "puntaje": float(m["puntaje_phishing"]), "nivel": m["nivel"]}
        for m in res.mappings()
    ]
