import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ESTADO_CAMPANA = ("pendiente", "programada", "activa", "completada", "cancelada")


class Campana(Base):
    __tablename__ = "campanas"

    id_campanas: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizaciones.id_organizaciones", ondelete="CASCADE"), nullable=False
    )
    grupo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grupos.id_grupos", ondelete="RESTRICT"), nullable=False
    )
    plantilla_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plantillas.id_plantillas", ondelete="SET NULL"), nullable=True
    )
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    estado: Mapped[str] = mapped_column(PgEnum(*ESTADO_CAMPANA, name="estado_campana"), nullable=False, default="pendiente")
    programada_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    iniciada_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizada_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    feedback_enviado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")


class CampanaCanal(Base):
    __tablename__ = "campana_canales"

    campana_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campanas.id_campanas", ondelete="CASCADE"), primary_key=True
    )
    canal: Mapped[str] = mapped_column(PgEnum("correo", "qr", name="tipo_canal"), primary_key=True)


class DestinatarioCampana(Base):
    """Token único por destinatario×campaña. Guarda el hash SHA-256 del token, nunca el valor en claro (§6.4)."""
    __tablename__ = "destinatarios_campana"
    __table_args__ = (UniqueConstraint("campana_id", "destinatario_id", name="uk_destinatario_campana"),)

    id_destinatarios_campana: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campana_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campanas.id_campanas", ondelete="CASCADE"), nullable=False
    )
    destinatario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("destinatarios.id_destinatarios", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    abierto_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    clic_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    enviado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
