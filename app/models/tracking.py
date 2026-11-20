import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIPO_EVENTO = ("abierto", "click", "subido")

class EventoTracking(Base):
    __tablename__ = "eventos_tracking"

    id_eventos_tracking: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destinatario_campana_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("destinatarios_campana.id_destinatarios_campana", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(PgEnum(*TIPO_EVENTO, name="tipo_evento"), nullable=False)
    canal_origen: Mapped[Optional[str]] = mapped_column(PgEnum("correo", "qr", name="tipo_canal"), nullable=True)
    direccion_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
