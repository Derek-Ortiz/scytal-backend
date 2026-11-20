import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log_event
from app.core.security import hash_password
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.repositories import organizacion_repository as org_repo
from app.repositories import usuario_repository as user_repo
from app.services.email_service import send_email
from app.services.usuario_service import _temp_password_valida

async def create_org(
    db: AsyncSession, nombre: str, slug: str | None, correo_admin: str | None, actor_id: str | None, request_id: str
) -> dict:
    """Crea la organización (y opcionalmente su primer admin_organizacion). Solo admin_plataforma."""
    slug_final = slug if slug else org_repo.slugify(nombre)
    if await org_repo.find_by_slug(db, slug_final):
        raise ValueError("el slug de organización ya está en uso")
    if correo_admin and await user_repo.find_by_email(db, correo_admin.lower().strip()):
        raise ValueError("ya existe un usuario con ese correo")

    org = await org_repo.create(db, nombre=nombre, slug=slug_final)
    await user_repo.save_audit(db, org.id_organizaciones, "org_created", f"Organización creada: {org.nombre} ({org.slug})")

    admin = None
    correo_enviado = None
    if correo_admin:
        correo_norm = correo_admin.lower().strip()
        contrasena = await _temp_password_valida()
        admin = Usuario(
            org_id=org.id_organizaciones,
            correo=correo_norm,
            rol="admin_organizacion",
            hash_contrasena=hash_password(contrasena),
            estado="pendiente_2fa",
            activo=True,
            debe_cambiar_contrasena=True,
        )
        await user_repo.add_user(db, admin)
        await user_repo.add_history(db, admin.id_usuarios, admin.hash_contrasena)
        await user_repo.save_audit(
            db, org.id_organizaciones, "invite_user", f"Alta de admin_organizacion {correo_norm}", actor_id=None
        )

    await db.commit()

    if correo_admin:
        url_login = get_settings().FRONTEND_BASE_URL.rstrip("/")
        asunto = f"Has sido nombrado admin de {org.nombre} en Scytal"
        texto = (
            f"Hola,\n\nFuiste nombrado(a) admin de la organización «{org.nombre}» en Scytal.\n\n"
            f"Tus credenciales temporales:\n  Correo: {correo_admin.lower()}\n  Contraseña temporal: {contrasena}\n\n"
            f"Ingresa en {url_login} con estas credenciales.\n"
            "En el primer inicio de sesión deberás: (1) activar la verificación en dos pasos (obligatoria) y "
            "(2) cambiar tu contraseña.\n\nScytal — Simulaciones de concientización de seguridad."
        )
        html = (
            f"<p>Hola,</p><p>Fuiste nombrado(a) <strong>admin</strong> de la organización "
            f"<strong>{org.nombre}</strong> en Scytal.</p>"
            f"<p>Tus credenciales temporales:<br>Correo: <code>{correo_admin.lower()}</code><br>"
            f"Contraseña temporal: <code>{contrasena}</code></p>"
            f"<p><a href=\"{url_login}\">Iniciar sesión en Scytal</a></p>"
            f"<p>En el primer inicio de sesión deberás activar 2FA (obligatorio) y cambiar tu contraseña.</p>"
        )
        correo_enviado = await send_email(correo_admin.lower(), asunto, texto, html, request_id=request_id)

    log_event("org_created", request_id=request_id, org_id=str(org.id_organizaciones), admin_created=bool(correo_admin))
    return {"org": org, "admin": admin, "correo_enviado": correo_enviado}

async def patch_org(db: AsyncSession, org: Organizacion, nombre: str | None, slug: str | None, actor: Usuario, request_id: str) -> Organizacion:
    if slug and slug != org.slug:
        if await org_repo.find_by_slug(db, slug):
            raise ValueError("el slug de organización ya está en uso")
    org = await org_repo.update(db, org, nombre=nombre, slug=slug)
    await user_repo.save_audit(db, org.id_organizaciones, "org_updated", f"Organización editada por {actor.correo}", actor_id=actor.id_usuarios)
    await db.commit()
    log_event("org_updated", request_id=request_id, org_id=str(org.id_organizaciones))
    return org
