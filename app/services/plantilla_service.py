"""Lógica de /templates (§4.7).

- Leyenda obligatoria (decisión): toda landing lleva la marca "PÁGINA DE PRUEBA"; el servicio
  la añade al final si el HTML no la trae. No se permiten landings sin aviso.
- Plantillas globales (org_id NULL): las lee toda organización, solo su dueña las edita
  (el router responde 403 para las ajenas).
- DELETE bloqueado si una campaña pendiente/programada/activa la referencia (→ 409);
  campañas viejas la sueltan con ON DELETE SET NULL.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.models.plantilla import Plantilla
from app.models.usuario import Usuario
from app.repositories import plantilla_repository as plantilla_repo
from app.repositories import usuario_repository as user_repo

LEYENDA = "PÁGINA DE PRUEBA"
LEYENDA_HTML = (
    '<div style="margin-top:24px;padding:14px;text-align:center;font-family:Arial,sans-serif;'
    'background:#f8d7da;color:#58151c;border-top:2px solid #f5c2c7;font-size:14px;">'
    '<strong>PÁGINA DE PRUEBA</strong> — simulacro de phishing de Scytal con fines educativos. '
    'Ninguna credencial fue enviada a un servicio real.</div>'
)


def aplicar_leyenda(landing_html: str) -> str:
    """Añade la leyenda al final si el HTML no la trae ya (case-insensitive)."""
    if LEYENDA.lower() in landing_html.lower():
        return landing_html
    return landing_html + LEYENDA_HTML


async def create_plantilla(
    db: AsyncSession, org_id: uuid.UUID, nombre: str, perfil: str, canal: str,
    asunto: str | None, contenido_html: str, landing_html: str,
    actor: Usuario, request_id: str,
) -> Plantilla:
    p = await plantilla_repo.create(
        db, org_id, nombre, perfil, canal, asunto,
        contenido_html, aplicar_leyenda(landing_html),
    )
    await user_repo.save_audit(
        db, org_id, "template_created", f"Plantilla creada: {p.nombre} (canal {p.canal})",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("template_created", request_id=request_id, plantilla_id=str(p.id_plantillas), org_id=str(org_id))
    return p


async def update_plantilla(
    db: AsyncSession, plantilla: Plantilla,
    nombre: str | None, perfil: str | None, canal: str | None,
    asunto: str | None, contenido_html: str | None, landing_html: str | None,
    actor: Usuario, request_id: str,
) -> Plantilla:
    """PATCH parcial. La regla final canal⇒asunto (§5) se evalúa con el estado resultante.

    Invariantes de negocio:
    - algo que editar (el router ya lo valida, aquí defensa extra);
    - canal=correo ⇒ asunto no vacío → ValueError (el router responde 422);
    - la landing editada siempre termina con la leyenda obligatoria.
    """
    if plantilla.org_id is None:
        # defensa extra: las globales no se editan desde aquí (el router ya responde 403)
        raise PermissionError("una plantilla global no se puede editar desde una organización")

    canal_final = canal or plantilla.canal
    asunto_final = asunto if asunto is not None else plantilla.asunto
    if canal_final == "correo" and (asunto_final is None or not asunto_final.strip()):
        raise ValueError("asunto es obligatorio cuando canal = 'correo'")

    p = await plantilla_repo.update(
        db, plantilla,
        nombre=nombre, perfil=perfil, canal=canal,
        asunto=asunto, contenido_html=contenido_html,
        landing_html=aplicar_leyenda(landing_html) if landing_html is not None else None,
    )
    await user_repo.save_audit(
        db, plantilla.org_id, "template_updated", f"Plantilla editada: {p.nombre}",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("template_updated", request_id=request_id, plantilla_id=str(p.id_plantillas))
    return p


async def delete_plantilla(db: AsyncSession, plantilla: Plantilla, actor: Usuario, request_id: str) -> None:
    """DELETE solo si ninguna campaña pendiente/programada/activa la referencia (§4.7 → 409)."""
    if plantilla.org_id is None:
        raise PermissionError("una plantilla global no se puede eliminar desde una organización")
    if await plantilla_repo.en_uso(db, plantilla.id_plantillas):
        raise ValueError("la plantilla está en uso por una campaña pendiente o activa")
    org_id = plantilla.org_id
    nombre = plantilla.nombre
    await plantilla_repo.delete(db, plantilla)
    await user_repo.save_audit(
        db, org_id, "template_deleted", f"Plantilla eliminada: {nombre}", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("template_deleted", request_id=request_id, org_id=str(org_id))
