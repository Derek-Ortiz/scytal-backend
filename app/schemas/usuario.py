import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import CorreoStr, _norm_email

class UsuarioResponse(BaseModel):
    id_usuarios: uuid.UUID
    correo: str
    rol: str
    estado: str
    activo: bool
    creado_en: datetime

class UsuarioListResponse(BaseModel):
    total: int
    items: list[UsuarioResponse]
    limit: int
    offset: int

class InviteRequest(BaseModel):
    """Invitación de analista a la propia organización (rol fijo por §5: nunca admin vía esta ruta)."""
    correo: CorreoStr

    _norm = field_validator("correo", mode="before")(_norm_email)

class InviteResponse(BaseModel):
    id_usuarios: uuid.UUID
    correo: str
    rol: str
    estado: str
    correo_enviado: bool  

class RoleChangeRequest(BaseModel):
    rol: str 

    @field_validator("rol")
    @classmethod
    def _valid_rol(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("analista", "admin_organizacion"):
            raise ValueError("rol debe ser 'analista' o 'admin_organizacion'")
        return v

class PaginacionParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
