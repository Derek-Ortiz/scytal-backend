"""Schemas de /organizations (§4.3 + métricas para admin_plataforma, decisión #7)."""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import _valid_slug


class OrganizacionCreateRequest(BaseModel):
    nombre: str = Field(min_length=2, max_length=255)
    slug: Optional[str] = None
    # Opcional: si se envía, crea además el admin_organizacion de la org con contraseña temporal
    # (estado pendiente_2fa + cambio forzado en el primer login) y le envía el correo de invitación.
    correo_admin: Optional[str] = Field(default=None, max_length=254)

    _valid_slug_f = field_validator("slug", mode="before")(lambda v: _valid_slug(v) if v not in (None, "") else None)


class OrganizacionPatchRequest(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=2, max_length=255)
    slug: Optional[str] = None

    _valid_slug_f = field_validator("slug", mode="before")(lambda v: _valid_slug(v) if v not in (None, "") else None)


class OrganizacionMetrics(BaseModel):
    usuarios_activos: int = 0
    grupos: int = 0
    destinatarios_activos: int = 0
    campanas_totales: int = 0
    campanas_activas: int = 0


class OrganizacionResponse(BaseModel):
    id_organizaciones: uuid.UUID
    nombre: str
    slug: str
    creado_en: datetime


class OrganizacionDetailResponse(OrganizacionResponse):
    metricas: OrganizacionMetrics


class OrganizacionListResponse(BaseModel):
    total: int
    items: list[OrganizacionDetailResponse]
    limit: int
    offset: int


class OrganizacionCreateResponse(BaseModel):
    organizacion: OrganizacionResponse
    admin: Optional[dict] = None  # {id_usuarios, correo, contrasena_temporal_enviada}
