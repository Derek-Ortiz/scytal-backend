"""Schemas de /templates (§4.7).

Regla §5: si canal = correo, `asunto` es obligatorio — validado AQUÍ (schema), no solo en BD.
Plantillas globales tienen org_id NULL: las lee toda organización; solo las edita su dueña
(una org solo puede PATCH/DELETE las propias).
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CANALES = ("correo", "qr")


def _no_vacio(v: str | None) -> str | None:
    if v is not None and not v.strip():
        raise ValueError("no puede estar vacío o ser solo espacios")
    return v


def _valid_canal(v: str) -> str:
    if v not in CANALES:
        raise ValueError("canal inválido: solo 'correo' o 'qr'")
    return v


class PlantillaCreateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    perfil: str = Field(min_length=1, max_length=100)
    canal: str = Field(min_length=1, max_length=20)
    asunto: Optional[str] = Field(default=None, max_length=255)
    contenido_html: str = Field(min_length=1)
    landing_html: str = Field(min_length=1)

    _v = field_validator("nombre", "perfil", "asunto", "contenido_html", "landing_html")(_no_vacio)
    _v_canal = field_validator("canal")(_valid_canal)

    @model_validator(mode="after")
    def _correo_requiere_asunto(self):
        if self.canal == "correo" and (self.asunto is None or not self.asunto.strip()):
            raise ValueError("asunto es obligatorio cuando canal = 'correo'")
        return self


class PlantillaPatchRequest(BaseModel):
    """PATCH parcial: la regla final canal⇒asunto se valida en el servicio (necesita el valor guardado)."""

    nombre: Optional[str] = Field(default=None, min_length=1, max_length=255)
    perfil: Optional[str] = Field(default=None, min_length=1, max_length=100)
    canal: Optional[str] = Field(default=None, min_length=1, max_length=20)
    asunto: Optional[str] = Field(default=None, max_length=255)
    contenido_html: Optional[str] = Field(default=None, min_length=1)
    landing_html: Optional[str] = Field(default=None, min_length=1)

    _v = field_validator("nombre", "perfil", "asunto", "contenido_html", "landing_html")(_no_vacio)
    _v_canal = field_validator("canal")(_valid_canal)


class PlantillaImportarRequest(BaseModel):
    """POST /templates/importar (decisión: clonado de página real por URL).

    Opción A (descarga estática httpx) con fallback automático a Opción B (Chromium headless
    vía Playwright) cuando el HTML llega como carcasa vacía de un SPA 100% JavaScript.
    """

    url: str = Field(min_length=8, max_length=2048)
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=255)
    perfil: str = Field(default="corporativo", min_length=1, max_length=100)
    canal: str = Field(default="correo", min_length=1, max_length=20)
    asunto: Optional[str] = Field(default=None, max_length=255)

    _v = field_validator("nombre", "perfil", "asunto")(_no_vacio)
    _v_canal = field_validator("canal")(_valid_canal)


class PlantillaPreviewResponse(BaseModel):
    """GET /templates/{id}/previsualizar: enlace efímero (JWT 30 min) con la landing EXACTA
    que verá el destinatario; se abre directo en el navegador."""

    url: str
    expira_en_minutos: int


class PlantillaResponse(BaseModel):
    id_plantillas: uuid.UUID
    org_id: Optional[uuid.UUID] = None  # None = plantilla global (visible para todas las orgs)
    nombre: str
    perfil: str
    canal: str
    asunto: Optional[str] = None
    contenido_html: str
    landing_html: str
    creado_en: datetime
    actualizado_en: datetime


class PlantillaDetailResponse(PlantillaResponse):
    """Detalle con `en_uso`: referenciada por alguna campaña en pendiente/programada/activa."""

    en_uso: bool = False


class PlantillaListResponse(BaseModel):
    total: int
    items: list[PlantillaDetailResponse]
    limit: int
    offset: int
