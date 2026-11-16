import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

NIVEL_MADUREZ = ("bajo", "medio", "alto", "critico")


class InstantaneaPhishing(Base):
    """Índice de phishing por destinatario al finalizar una campaña (25% no abrir + 25% no clic + 50% no enviar)."""
    __tablename__ = "instantaneas_phishing"

    id_instantaneas_phishing: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizaciones.id_organizaciones", ondelete="CASCADE"), nullable=False
    )
    destinatario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("destinatarios.id_destinatarios", ondelete="CASCADE"), nullable=False
    )
    campana_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campanas.id_campanas", ondelete="SET NULL"), nullable=True
    )
    puntaje_phishing: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    nivel: Mapped[str] = mapped_column(PgEnum(*NIVEL_MADUREZ, name="nivel_madurez"), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
