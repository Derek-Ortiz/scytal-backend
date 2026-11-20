from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tracking import EventoTracking

async def registrar_evento(
    db: AsyncSession,
    destinatario_campana_id,
    tipo: str,
    *,
    canal_origen: str | None,
    direccion_ip: str | None,
    user_agent: str | None,
) -> None:
    """Inserta un evento (abierto|click|subido). El commit lo hace el caller (/track)."""
    db.add(EventoTracking(
        destinatario_campana_id=destinatario_campana_id,
        tipo=tipo,
        canal_origen=canal_origen,
        direccion_ip=direccion_ip,
        user_agent=user_agent,
    ))
    await db.flush()
