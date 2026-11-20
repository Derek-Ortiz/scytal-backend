import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, get_current_user, require_roles
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.repositories import organizacion_repository as org_repo
from app.repositories import usuario_repository as user_repo
from app.schemas.auth import error_payload
from app.schemas.usuario import (
    InviteRequest, InviteResponse, RoleChangeRequest, UsuarioListResponse, UsuarioResponse,
)
from app.services import usuario_service

router = APIRouter(prefix="/users", tags=["users"])

def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())

def _user_response(u: Usuario) -> UsuarioResponse:
    return UsuarioResponse(id_usuarios=u.id_usuarios, correo=u.correo, rol=u.rol, estado=u.estado, activo=u.activo, creado_en=u.creado_en)

@router.get("", response_model=UsuarioListResponse)
async def list_users(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Usuarios de la PROPIA organización (org_id del JWT; admin_organizacion y analista)."""
    total, users = await user_repo.list_by_org(db, org_id, limit, offset)
    return UsuarioListResponse(total=total, items=[_user_response(u) for u in users], limit=limit, offset=offset)

@router.post("/invite", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Invita un analista a la propia organización (§5: por esta vía nunca se crea un admin)."""
    org = await org_repo.find_by_id(db, org_id)
    if org is None:
        _raise("NOT_FOUND", "Organización no encontrada", 404)
    try:
        result = await usuario_service.invite_analista(
            db, org, body.correo, actor, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        if "ya existe" in str(e):
            _raise("DUPLICATE", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return InviteResponse(
        id_usuarios=result["user"].id_usuarios,
        correo=result["user"].correo,
        rol=result["user"].rol,
        estado=result["user"].estado,
        correo_enviado=result["correo_enviado"],
    )

@router.patch("/{user_id}/role", response_model=UsuarioResponse)
async def change_role(
    user_id: uuid.UUID,
    body: RoleChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    target = await user_repo.find_by_id_in_org(db, user_id, org_id)
    if target is None:
        _raise("NOT_FOUND", "Usuario no encontrado en tu organización", 404)
    try:
        target = await usuario_service.change_role(db, target, body.rol, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)
    return _user_response(target)

@router.patch("/{user_id}/deactivate", response_model=UsuarioResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Borrado lógico (§4.4): conserva datos; mata sesiones activas del usuario."""
    target = await user_repo.find_by_id_in_org(db, user_id, org_id)
    if target is None:
        _raise("NOT_FOUND", "Usuario no encontrado en tu organización", 404)
    try:
        target = await usuario_service.deactivate(db, target, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)
    return _user_response(target)
