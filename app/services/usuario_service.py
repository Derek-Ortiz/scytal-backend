"""Lógica de negocio de /users (§4.4).

Invitación: contraseña temporal aleatoria (cumple §5), estado pendiente_2fa y cambio FORZOSO
en el primer login (debe_cambiar_contrasena=True; las rutas de negocio responden
PASSWORD_CHANGE_REQUIRED hasta que cambie — decisión #11 del usuario).
Los datos de usuarios desactivados se conservan sin anonimizar (decisión #9).
"""
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log_event
from app.core.security import hash_password
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.repositories import usuario_repository as user_repo
from app.services.email_service import send_email
from app.services.password_service import validate_password


def generate_temp_password() -> str:
    """Contraseña temporal aleatoria (token_urlsafe): 16+ caracteres, pasa §5 sin ser diccionaria."""
    return secrets.token_urlsafe(14)


async def _temp_password_valida() -> str:
    for _ in range(5):
        pw = generate_temp_password()
        if not await validate_password(pw):
            return pw
    raise RuntimeError("No se pudo generar una contraseña temporal válida")


def _correo_invitacion(correo: str, nombre_org: str, contrasena: str) -> tuple[str, str, str]:
    """(asunto, texto, html) del correo de invitación."""
    url_login = get_settings().FRONTEND_BASE_URL.rstrip("/")
    asunto = f"Has sido invitado a Scytal — {nombre_org}"
    texto = (
        f"Hola,\n\nHas sido invitado(a) como analista de seguridad de la organización «{nombre_org}» en Scytal.\n\n"
        f"Tus credenciales temporales:\n  Correo: {correo}\n  Contraseña temporal: {contrasena}\n\n"
        f"Ingresa en {url_login} con estas credenciales.\n"
        "En el primer inicio de sesión deberás: (1) activar la verificación en dos pasos (obligatoria) y "
        "(2) cambiar tu contraseña.\n\nScytal — Simulaciones de concientización de seguridad."
    )
    html = (
        f"<p>Hola,</p>"
        f"<p>Has sido invitado(a) como <strong>analista de seguridad</strong> de la organización "
        f"<strong>{nombre_org}</strong> en Scytal.</p>"
        f"<p>Tus credenciales temporales:<br>Correo: <code>{correo}</code><br>"
        f"Contraseña temporal: <code>{contrasena}</code></p>"
        f"<p><a href=\"{url_login}\">Iniciar sesión en Scytal</a></p>"
        f"<p>En el primer inicio de sesión deberás: (1) activar la verificación en dos pasos (obligatoria) y "
        f"(2) cambiar tu contraseña.</p>"
        f"<p style='color:#888;font-size:12px'>Scytal — Simulaciones de concientización de seguridad.</p>"
    )
    return asunto, texto, html


async def invite_analista(db: AsyncSession, org: Organizacion, correo: str, actor: Usuario, request_id: str) -> dict:
    """Crea un analista invitado y le envía sus credenciales temporales por correo."""
    correo_norm = correo.lower().strip()
    if await user_repo.find_by_email(db, correo_norm):
        raise ValueError("ya existe un usuario con ese correo")

    contrasena = await _temp_password_valida()
    user = Usuario(
        org_id=org.id_organizaciones,
        correo=correo_norm,
        rol="analista",  # §5: por esta vía NUNCA se crea admin_organizacion ni admin_plataforma
        hash_contrasena=hash_password(contrasena),
        estado="pendiente_2fa",
        activo=True,
        debe_cambiar_contrasena=True,
    )
    await user_repo.add_user(db, user)
    await user_repo.add_history(db, user.id_usuarios, user.hash_contrasena)
    await user_repo.save_audit(
        db, org.id_organizaciones, "invite_user", f"Invitación de analista a {correo_norm}", actor_id=actor.id_usuarios
    )
    await db.commit()

    asunto, texto, html = _correo_invitacion(correo_norm, org.nombre, contrasena)
    enviado = await send_email(correo_norm, asunto, texto, html, request_id=request_id)
    log_event("invite_user", request_id=request_id, user_id=str(user.id_usuarios), email_sent=enviado)
    return {"user": user, "correo_enviado": enviado}


async def change_role(db: AsyncSession, target: Usuario, nuevo_rol: str, actor: Usuario, request_id: str) -> Usuario:
    if target.id_usuarios == actor.id_usuarios:
        raise ValueError("no puedes cambiar tu propio rol")
    if target.rol == nuevo_rol:
        raise ValueError("el usuario ya tiene ese rol")
    # No dejar a la organización sin admin_organizacion
    if target.rol == "admin_organizacion" and nuevo_rol != "admin_organizacion":
        admins = await user_repo.count_by_role(db, target.org_id, "admin_organizacion")
        if admins <= 1:
            raise ValueError("no puedes quitar el rol: es el último admin_organizacion de la organización")
    rol_previo = target.rol
    target.rol = nuevo_rol
    await user_repo.save_audit(
        db, target.org_id, "role_change", f"Rol de {target.correo}: {rol_previo} → {nuevo_rol}", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("role_change", request_id=request_id, target_id=str(target.id_usuarios), rol=nuevo_rol)
    return target


async def deactivate(db: AsyncSession, target: Usuario, actor: Usuario, request_id: str) -> Usuario:
    """Borrado lógico (§4.4): conserva datos, mata sesiones activas (version_token+1)."""
    if target.id_usuarios == actor.id_usuarios:
        raise ValueError("no puedes desactivarte a ti mismo")
    if not target.activo:
        raise ValueError("el usuario ya está desactivado")
    target.activo = False
    target.estado = "inactivo"
    target.version_token += 1  # invalida JWT en circulación (§auth)
    await user_repo.save_audit(
        db, target.org_id, "user_deactivated", f"Desactivación de {target.correo} (datos conservados)", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("user_deactivated", request_id=request_id, target_id=str(target.id_usuarios))
    return target
