"""Schemas de /campaigns (§4.8).

Decisión de diseño: el "draft" del spec es el estado `pendiente` del enum de BD.
La expiración (horas) la define el usuario y es editable también con la campaña activa
(→ re-datura expira_en de todos los tokens). El canal `qr` es anónimo y exige zonas.
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.plantilla import CANALES


def _no_vacio(v: str | None) -> str | None:
    if v is not None and not v.strip():
        raise ValueError("no puede estar vacío o ser solo espacios")
    return v


class CampanaCreateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    grupo_id: uuid.UUID
    plantilla_id: Optional[uuid.UUID] = None
    expiracion_horas: int = Field(default=72, ge=1, le=8760)

    _v = field_validator("nombre")(_no_vacio)


class CampanaPatchRequest(BaseModel):
    """Con `activa` SOLO se permite expiracion_horas (validado en el servicio → 409 si no)."""

    nombre: Optional[str] = Field(default=None, min_length=1, max_length=255)
    grupo_id: Optional[uuid.UUID] = None
    plantilla_id: Optional[uuid.UUID] = None
    expiracion_horas: Optional[int] = Field(default=None, ge=1, le=8760)

    _v = field_validator("nombre")(_no_vacio)


class CampanaChannelsRequest(BaseModel):
    """Define canales en `campana_canales`. Solo con la campaña en `pendiente`.

    - `canales`: al menos uno; valores válidos correo|qr.
    - `zonas`: obligatorias si va `qr` (decisión: el QR anónimo nunca queda sin zona).
    """

    canales: list[str] = Field(min_length=1, max_length=2)
    zonas: Optional[list[str]] = Field(default=None, max_length=50)

    @field_validator("canales")
    def _canales_validos(cls, v: list[str]) -> list[str]:
        for c in v:
            if c not in CANALES:
                raise ValueError("canal inválido: solo 'correo' o 'qr'")
        if len(set(v)) != len(v):
            raise ValueError("canales duplicados")
        return v

    @field_validator("zonas")
    def _zonas_validas(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        limpias = []
        for z in v:
            z = z.strip()
            if not z or len(z) > 100:
                raise ValueError("cada zona debe tener entre 1 y 100 caracteres")
            limpias.append(z)
        if len(set(z.lower() for z in limpias)) != len(limpias):
            raise ValueError("zonas duplicadas")
        return limpias

    @model_validator(mode="after")
    def _qr_requiere_zonas(self):
        hay_qr = "qr" in self.canales
        hay_zonas = bool(self.zonas)
        if hay_qr and not hay_zonas:
            raise ValueError("el canal 'qr' requiere al menos una zona")
        if not hay_qr and hay_zonas:
            raise ValueError("las zonas solo aplican al canal 'qr'")
        return self


class CampanaLaunchRequest(BaseModel):
    """Cuerpo opcional del launch: si envía expiracion_horas, sobrescribe la guardada."""

    expiracion_horas: Optional[int] = Field(default=None, ge=1, le=8760)


# ---- Respuestas ----

class CampanaCanalResponse(BaseModel):
    canal: str
    zonas: list[str] = []


class CampanaResponse(BaseModel):
    id_campanas: uuid.UUID
    org_id: uuid.UUID
    grupo_id: uuid.UUID
    plantilla_id: Optional[uuid.UUID] = None
    nombre: str
    estado: str
    expiracion_horas: int
    programada_en: Optional[datetime] = None
    iniciada_en: Optional[datetime] = None
    finalizada_en: Optional[datetime] = None
    feedback_enviado_en: Optional[datetime] = None
    creado_en: datetime
    actualizado_en: datetime
    canales: list[CampanaCanalResponse] = []


CampanaDetailResponse = CampanaResponse


class CampanaListResponse(BaseModel):
    total: int
    items: list[CampanaResponse]
    limit: int
    offset: int


class CampanaStatsResponse(BaseModel):
    """Embudo §4.8: enviados/abiertos/clics/enviados-datos sobre los tokens de destinatario.

    `qr_clics` es anónimo (no atribuido a nadie): se reporta aparte, nunca entra al embudo.
    """

    campana_id: uuid.UUID
    estado: str
    total_destinatarios: int
    enviados: int
    abiertos: int
    clics: int
    subidos: int
    qr_clics: int = 0


class CampanaRecipienteRow(BaseModel):
    destinatario_id: uuid.UUID
    correo: str
    enviado: bool
    abrio: bool
    clico: bool
    subio: bool
    expira_en: datetime
    vencido: bool
    puntaje_phishing: Optional[float] = None
    nivel: Optional[str] = None


class CampanaRecipientsResponse(BaseModel):
    campana_id: uuid.UUID
    total: int
    items: list[CampanaRecipienteRow]
    limit: int
    offset: int


class QrZonaUrlResponse(BaseModel):
    zona: str
    url: str
    qr_base64: str


class CampanaQrResponse(BaseModel):
    campana_id: uuid.UUID
    zonas: list[QrZonaUrlResponse]


class CampanaFinishResponse(BaseModel):
    campana: CampanaResponse
    instantaneas: int
    alertas: int


class CampanaLaunchResponse(BaseModel):
    campana: CampanaResponse
    emails_programados: int
    zonas_qr: int


class CampanaFeedbackResponse(BaseModel):
    ok: bool = True
    message: str
    emails_programados: int
