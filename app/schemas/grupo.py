"""Schemas de /groups (§4.5)."""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _no_vacio(v: str | None) -> str | None:
    if v is not None and not v.strip():
        raise ValueError("no puede estar vacío o ser solo espacios")
    return v


class GrupoCreateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    perfil: str = Field(min_length=1, max_length=100)

    _v = field_validator("nombre", "perfil")(_no_vacio)


class GrupoPatchRequest(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=150)
    perfil: Optional[str] = Field(default=None, min_length=1, max_length=100)

    _v = field_validator("nombre", "perfil")(_no_vacio)


class GrupoResponse(BaseModel):
    id_grupos: uuid.UUID
    nombre: str
    perfil: str
    creado_en: datetime


class GrupoMetrics(BaseModel):
    destinatarios_activos: int = 0
    indice_promedio: Optional[float] = None  # promedio del último puntaje por destinatario (None = sin datos)


class GrupoDetailResponse(GrupoResponse):
    metricas: GrupoMetrics


class GrupoListResponse(BaseModel):
    total: int
    items: list["GrupoDetailResponse"]
    limit: int
    offset: int
