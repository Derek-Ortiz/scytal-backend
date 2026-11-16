import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIPO_CANAL = ("correo", "qr")


class Plantilla(Base):
    __tablename__ = "plantillas"

    id_plantillas: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizaciones.id_organizaciones", ondelete="CASCADE"), nullable=True
    )
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    perfil: Mapped[str] = mapped_column(String(100), nullable=False)
    canal: Mapped[str] = mapped_column(PgEnum(*TIPO_CANAL, name="tipo_canal"), nullable=False)
    asunto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contenido_html: Mapped[str] = mapped_column(Text, nullable=False)
    landing_html: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
