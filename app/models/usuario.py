import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ROL_USUARIO = ("admin_plataforma", "admin_organizacion", "analista")
ESTADO_USUARIO = ("pendiente_2fa", "activo", "suspendido", "inactivo")


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(
            "(rol = 'admin_plataforma' AND org_id IS NULL) OR (rol IN ('admin_organizacion', 'analista') AND org_id IS NOT NULL)",
            name="chk_usuarios_org_segun_rol",
        ),
    )

    id_usuarios: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizaciones.id_organizaciones", ondelete="CASCADE"), nullable=True
    )
    correo: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    rol: Mapped[str] = mapped_column(PgEnum(*ROL_USUARIO, name="rol_usuario"), nullable=False)
    hash_contrasena: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secreto_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_habilitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ultimo_totp_step: Mapped[int | None] = mapped_column(nullable=True)
    contrasena_actualizada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
    debe_cambiar_contrasena: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version_token: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    estado: Mapped[str] = mapped_column(PgEnum(*ESTADO_USUARIO, name="estado_usuario"), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="CURRENT_TIMESTAMP")
