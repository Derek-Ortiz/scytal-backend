import base64
import io
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import qrcode
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log_event
from app.core.security import (
    create_access_token, create_pending_token, create_refresh_token,
    decrypt_totp_secret, decode_token, encrypt_totp_secret,
    generate_totp_secret, hash_password, totp_provisioning_uri,
    verify_password, verify_totp,
)
from app.models.auditoria import EventoAuditoria  # noqa: F401
from app.models.historial import HistorialContrasenas
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.repositories import organizacion_repository as org_repo
from app.repositories import usuario_repository as user_repo
from app.services.password_service import validate_password

ROTATE_DAYS = 90


def _password_expired(user: Usuario) -> bool:
    if user.contrasena_actualizada_en is None:
        return True
    updated = user.contrasena_actualizada_en
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated > timedelta(days=ROTATE_DAYS)


# ---------- Register ----------
async def register(db: AsyncSession, correo: str, contrasena: str, nombre_org: str, slug: str | None, request_id: str) -> tuple[Usuario, Organizacion]:
    correo_norm = correo.lower().strip()
    from app.core.security import needs_rehash  # noqa

    errors = await validate_password(contrasena)
    if errors:
        raise ValueError("; ".join(errors))

    if await user_repo.find_by_email(db, correo_norm):
        raise ValueError("ya existe un usuario con ese correo")

    final_slug = (slug.strip().lower() if slug else org_repo.slugify(nombre_org))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", final_slug):
        raise ValueError("slug inválido")
    if await org_repo.find_by_slug(db, final_slug):
        raise ValueError("el slug de organización ya está en uso")

    org = await org_repo.create(db, nombre=nombre_org, slug=final_slug)
    h = hash_password(contrasena)
    user = Usuario(
        org_id=org.id_organizaciones, correo=correo_norm, rol="admin_organizacion",
        hash_contrasena=h, estado="pendiente_2fa", activo=True, debe_cambiar_contrasena=False,
    )
    await user_repo.add_user(db, user)
    await user_repo.add_history(db, user.id_usuarios, h)
    await user_repo.save_audit(db, org.id_organizaciones, "register", f"Registro de {correo_norm}", actor_id=user.id_usuarios)
    log_event("register", request_id=request_id, user_id=str(user.id_usuarios))
    await db.commit()
    return user, org


# ---------- Login ----------
class LoginResult(BaseModel):
    requires_totp: bool = True
    must_enroll_totp: bool = False
    pending_token: Optional[str] = None
    provisional_access_token: Optional[str] = None
    requires_password_change: bool = False


# ---------- Login ----------
async def login(db: AsyncSession, correo: str, contrasena: str, ip: str, request_id: str) -> dict:
    correo_norm = correo.lower().strip()
    user = await user_repo.find_by_email(db, correo_norm)
    if user is None or not user.activo or not verify_password(contrasena, user.hash_contrasena):
        log_event("login_failed", request_id=request_id, correo=correo_norm)
        return {"ok": False}

    # auditoría solo si hay org (opción B)
    if user.org_id is not None:
        await user_repo.save_audit(db, user.org_id, "login_ok", f"Login de {correo_norm}", actor_id=user.id_usuarios)

    must_change = bool(user.debe_cambiar_contrasena) or _password_expired(user)
    s = get_settings()

    cuenta_sin_totp = user.totp_secreto_enc is None
    if cuenta_sin_totp:
        # Cuenta recién creada (pendiente_2fa sin secreto): token provisional solo para
        # enroll/confirm/me/logout/password-change (get_current_user bloquea rutas de negocio).
        log_event("login_provisional_totp", request_id=request_id, user_id=str(user.id_usuarios))
        return {
            "ok": True,
            "requires_totp": False,
            "must_enroll_totp": True,
            "pending_token": None,
            "provisional_access_token": create_access_token(
                str(user.id_usuarios), str(user.org_id) if user.org_id else None, user.rol, user.version_token
            ),
            "requires_password_change": must_change,
            "user": user,
        }

    pending = create_pending_token(str(user.id_usuarios), str(user.org_id) if user.org_id else None, user.rol)
    return {
        "ok": True,
        "requires_totp": True,
        "must_enroll_totp": False,
        "pending_token": pending,
        "provisional_access_token": None,
        "requires_password_change": must_change,
        "user": user,
    }


# ---------- Verify TOTP ----------
async def verify_totp_login(db: AsyncSession, pending_token: str, codigo: str, request_id: str) -> dict:
    try:
        claims = decode_token(pending_token)
    except jwt.InvalidTokenError:
        raise ValueError("token de sesión inválido o expirado")
    if claims.get("tipo") != "pending":
        raise ValueError("token de tipo incorrecto")

    user = await user_repo.find_by_id(db, uuid.UUID(claims["sub"]))
    if user is None or not user.activo:
        raise ValueError("usuario no válido")
    if not user.totp_secreto_enc:
        raise ValueError("2FA no configurado")
    secret = decrypt_totp_secret(user.totp_secreto_enc)
    ok, step = verify_totp(secret, codigo, user.ultimo_totp_step)
    if not ok:
        raise ValueError("código TOTP inválido")
    user.ultimo_totp_step = step

    # si el estado es pendiente_2fa y totp_habilitado, el usuario ya confirmó enroll; si aún no, sigue bloqueado
    if user.estado == "pendiente_2fa":
        # Se puede seguir sin pending: permitimos, el confirm lo activará
        pass

    await user_repo.save_audit(db, user.org_id, "login_totp_ok", "TOTP verificado", actor_id=user.id_usuarios)
    log_event("login_totp_ok", request_id=request_id, user_id=str(user.id_usuarios))
    await db.commit()

    s = get_settings()
    return {
        "access_token": create_access_token(str(user.id_usuarios), str(user.org_id) if user.org_id else None, user.rol, user.version_token),
        "refresh_token": create_refresh_token(str(user.id_usuarios), str(user.org_id) if user.org_id else None, user.rol, user.version_token),
        "expires_in_minutes": s.JWT_ACCESS_EXPIRE_MINUTES,
    }


# ---------- Refresh / logout ----------
async def refresh(db: AsyncSession, refresh_token: str) -> dict:
    try:
        claims = decode_token(refresh_token)
    except jwt.InvalidTokenError:
        raise ValueError("refresh token inválido o expirado")
    if claims.get("tipo") != "refresh":
        raise ValueError("token de tipo incorrecto")
    user = await user_repo.find_by_id(db, uuid.UUID(claims["sub"]))
    if user is None or not user.activo:
        raise ValueError("usuario no válido")
    if claims.get("version_token") != user.version_token:
        raise ValueError("sesión invalidada")
    s = get_settings()
    return {
        "access_token": create_access_token(str(user.id_usuarios), str(user.org_id) if user.org_id else None, user.rol, user.version_token),
        "refresh_token": create_refresh_token(str(user.id_usuarios), str(user.org_id) if user.org_id else None, user.rol, user.version_token),
        "expires_in_minutes": s.JWT_ACCESS_EXPIRE_MINUTES,
    }


async def logout(db: AsyncSession, user: Usuario) -> None:
    user.version_token += 1
    await user_repo.save_audit(db, user.org_id, "logout", "Logout", actor_id=user.id_usuarios)
    await db.commit()


# ---------- TOTP enroll / confirm ----------
def enroll_totp(user: Usuario) -> dict:
    secret = generate_totp_secret()
    user.totp_secreto_enc = encrypt_totp_secret(secret)
    user.totp_habilitado = False
    uri = totp_provisioning_uri(secret, user.correo)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"secreto_en_claro": secret, "uri": uri, "qr_base64": qr_b64}


async def confirm_totp(db: AsyncSession, user: Usuario, codigo: str) -> Usuario:
    if not user.totp_secreto_enc:
        raise ValueError("no hay secreto pendiente de confirmación")
    secret = decrypt_totp_secret(user.totp_secreto_enc)
    ok, step = verify_totp(secret, codigo, user.ultimo_totp_step)
    if not ok:
        raise ValueError("código TOTP inválido")
    user.ultimo_totp_step = step
    user.totp_habilitado = True
    user.estado = "activo"
    await user_repo.save_audit(db, user.org_id, "totp_confirm", "2FA confirmado", actor_id=user.id_usuarios)
    await db.commit()
    return user


# ---------- Password change ----------
async def change_password(db: AsyncSession, user: Usuario, actual: str, nueva: str) -> None:
    if not verify_password(actual, user.hash_contrasena):
        raise ValueError("contraseña actual incorrecta")
    recent = await user_repo.last_hashes(db, user.id_usuarios, limit=3)
    errors = await validate_password(nueva, recent_hashes=recent)
    if errors:
        raise ValueError("; ".join(errors))
    h = hash_password(nueva)
    user.hash_contrasena = h
    user.contrasena_actualizada_en = datetime.now(timezone.utc)
    user.debe_cambiar_contrasena = False
    user.version_token += 1
    await user_repo.add_history(db, user.id_usuarios, h)
    await user_repo.save_audit(db, user.org_id, "password_change", "Cambio de contraseña", actor_id=user.id_usuarios)
    await db.commit()
