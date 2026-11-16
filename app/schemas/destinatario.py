"""Schemas de /recipients (§4.6), incluida la importación por CSV."""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import CorreoStr, _norm_email


class DestinatarioCreateRequest(BaseModel):
    correo: CorreoStr
    grupo_id: uuid.UUID

    _norm = field_validator("correo", mode="before")(_norm_email)


class DestinatarioPatchRequest(BaseModel):
    correo: Optional[CorreoStr] = None
    grupo_id: Optional[uuid.UUID] = None

    @field_validator("correo", mode="before")
    @classmethod
    def _correo_opcional(cls, v):
        if v is None:
            return None
        v = _norm_email(v)
        return v if v else None  # "   " o "" → no-op (no se envió)


class DestinatarioResponse(BaseModel):
    id_destinatarios: uuid.UUID
    correo: str
    grupo_id: uuid.UUID
    activo: bool
    creado_en: datetime


class InstantaneaResponse(BaseModel):
    campana_id: Optional[uuid.UUID] = None
    puntaje_phishing: float
    nivel: str
    creado_en: datetime


class DestinatarioDetailResponse(DestinatarioResponse):
    historico: list[InstantaneaResponse] = []


class DestinatarioListResponse(BaseModel):
    total: int
    items: list[DestinatarioResponse]
    limit: int
    offset: int


class CSVImportResponse(BaseModel):
    total_filas: int
    creados: int
    duplicados: int      # repetidos dentro del archivo o ya existentes en la org
    invalidos: int       # correo mal formado o grupo inexistente en la org
    errores: list[str] = Field(default_factory=list)  # detalle por fila (máx 100)


class CSVImportMeta:
    """Encabezados esperados del CSV (decisión propia, documentada en el contrato):
    `correo,grupo` — grupo por NOMBRE (debe existir en la organización)."""
    ENCABEZADOS_ESPERADOS = ("correo", "grupo")
    MAX_ERRORES_REPORTE = 100
