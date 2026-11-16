"""Lógica de negocio de /groups (§4.5).

- Nombre único por organización (uk_grupos_org_nombre), comparación case-insensitive.
- DELETE bloqueado si el grupo tiene campañas asociadas (RESTRICT del esquema);
  los destinatarios del grupo se borran en cascada con él (ON DELETE CASCADE).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.models.grupo import Grupo
from app.models.usuario import Usuario
from app.repositories import grupo_repository as grupo_repo
from app.repositories import usuario_repository as user_repo


async def create_grupo(db: AsyncSession, org_id: uuid.UUID, nombre: str, perfil: str, actor: Usuario, request_id: str) -> Grupo:
    if await grupo_repo.find_by_nombre(db, org_id, nombre):
        raise ValueError("ya existe un grupo con ese nombre en tu organización")
    grupo = await grupo_repo.create(db, org_id, nombre, perfil)
    await user_repo.save_audit(
        db, org_id, "group_created", f"Grupo creado: {grupo.nombre} (perfil {grupo.perfil})", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("group_created", request_id=request_id, grupo_id=str(grupo.id_grupos))
    return grupo


async def update_grupo(
    db: AsyncSession, grupo: Grupo, nombre: str | None, perfil: str | None, actor: Usuario, request_id: str
) -> Grupo:
    if nombre is not None and nombre.strip().lower() != grupo.nombre.lower():
        if await grupo_repo.find_by_nombre(db, grupo.org_id, nombre):
            raise ValueError("ya existe un grupo con ese nombre en tu organización")
    grupo = await grupo_repo.update(db, grupo, nombre=nombre, perfil=perfil)
    await user_repo.save_audit(
        db, grupo.org_id, "group_updated", f"Grupo editado: {grupo.nombre}", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("group_updated", request_id=request_id, grupo_id=str(grupo.id_grupos))
    return grupo


async def delete_grupo(db: AsyncSession, grupo: Grupo, actor: Usuario, request_id: str) -> None:
    if await grupo_repo.has_campanas(db, grupo.id_grupos):
        raise ValueError("el grupo tiene campañas asociadas y no puede eliminarse")
    org_id, nombre = grupo.org_id, grupo.nombre
    await grupo_repo.delete(db, grupo)
    await user_repo.save_audit(db, org_id, "group_deleted", f"Grupo eliminado: {nombre}", actor_id=actor.id_usuarios)
    await db.commit()
    log_event("group_deleted", request_id=request_id, grupo_id=str(grupo.id_grupos))
