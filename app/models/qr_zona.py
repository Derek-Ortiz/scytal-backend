import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CampanaQrZona(Base):
    """Zona de un QR de campaña (decisión: canal QR anónimo con etiqueta de zona obligatoria).

    El QR se pega en una zona común (recepción, comedor...). Quien lo escanea NO queda
    atribuido a ningún destinatario: el token identifica campaña+zona, nunca a una persona.
    - token_qr: valor en claro que va dentro del QR (necesario para regenerar la imagen;
      no es un secreto personal: el propio póster lo exhibe públicamente).
    - token_hash: SHA-256 para validación en /track (§6.4, misma mecánica que los tokens
      de destinatario).
    """
    __tablename__ = "campanas_qr_zonas"
    __table_args__ = (UniqueConstraint("campana_id", "zona", name="uk_qr_zona"),)

    id_campanas_qr_zonas: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campana_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campanas.id_campanas", ondelete="CASCADE"), nullable=False
    )
    zona: Mapped[str] = mapped_column(String(100), nullable=False)
    token_qr: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    clic_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
