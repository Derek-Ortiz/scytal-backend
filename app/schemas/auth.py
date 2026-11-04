import re
import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Validador de correo estricto en formato (RFC 5322 simplificado, solo sintaxis).
# Se usa en lugar de EmailStr porque email-validator rechaza dominios reservados
# (p. ej. admin@scytal.local para MailHog en desarrollo), rompiendo el flujo local.
CORREO_RE = re.compile(
    r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def _validate_correo(v: str) -> str:
    v = v.strip()
    if len(v) > 254 or not CORREO_RE.fullmatch(v):
        raise ValueError("correo electrónico no válido")
    return v


class CorreoStr(str):
    """Tipo semántico para correo validado en formato."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(
            lambda v: _validate_correo(v) if isinstance(v, str) else v,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        return {"type": "string", "format": "email", "description": "correo electrónico validado en formato"}


def _norm_email(v: str) -> str:
    return v.strip().lower()


def _valid_slug(v: str) -> str:
    v = v.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", v):
        raise ValueError("slug inválido: solo minúsculas, números y guiones")
    return v


def _valid_password(v: str) -> str:
    if len(v) < 10:
        raise ValueError("La contraseña debe tener mínimo 10 caracteres")
    return v


# ---- Register ----
class RegisterRequest(BaseModel):
    correo: CorreoStr
    contrasena: str
    nombre_organizacion: str = Field(min_length=2, max_length=255)
    slug: Optional[str] = None

    _norm_correo = field_validator("correo", mode="before")(_norm_email)
    _valid_contra = field_validator("contrasena")(_valid_password)
    _valid_slug_f = field_validator("slug", mode="before")(lambda v: _valid_slug(v) if v not in (None, "") else None)


class RegisterResponse(BaseModel):
    id_usuarios: uuid.UUID
    correo: str
    rol: str
    estado: str
    org_id: uuid.UUID
    nombre_organizacion: str
    slug: str


# ---- Login ----
class LoginRequest(BaseModel):
    correo: CorreoStr
    contrasena: str

    _norm_correo = field_validator("correo", mode="before")(_norm_email)


class LoginResponse(BaseModel):
    requires_totp: bool = False
    must_enroll_totp: bool = False
    pending_token: Optional[str] = None
    provisional_access_token: Optional[str] = None
    requires_password_change: bool = False
    message: Optional[str] = None


class VerifyTotpRequest(BaseModel):
    codigo: str = Field(pattern=r"^\d{6}$")
    pending_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RefreshRequest(BaseModel):
    refresh_token: str


# ---- TOTP enroll / confirm ----
class TotpEnrollResponse(BaseModel):
    secreto_en_claro: str
    uri: str
    qr_base64: str


class TotpConfirmRequest(BaseModel):
    codigo: str = Field(pattern=r"^\d{6}$")


class ActionResponse(BaseModel):
    ok: bool = True
    message: Optional[str] = None


# ---- Password change ----
class PasswordChangeRequest(BaseModel):
    contrasena_actual: str
    contrasena_nueva: str

    _valid_nueva = field_validator("contrasena_nueva")(_valid_password)


# ---- Me ----
class MeResponse(BaseModel):
    id_usuarios: uuid.UUID
    correo: str
    rol: str
    estado: str
    org_id: Optional[uuid.UUID] = None
    activo: bool
    totp_habilitado: bool
    debe_cambiar_contrasena: bool


# ---- Error estándar §6.5 ----
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def error_payload(code: str, message: str, details: dict | None = None) -> ErrorResponse:
    return ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
