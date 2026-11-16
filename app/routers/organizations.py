"""Rutas /organizations (§4.3 + decisión #7). Aislamiento multi-tenant: org_id solo del JWT (§6.1)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_user, require_admin_plataforma
from app.models.usuario import Usuario
from app.repositories import organizacion_repository as org_repo
from app.schemas.organizacion import (
    OrganizacionCreateRequest, OrganizacionCreateResponse, OrganizacionDetailResponse,
    OrganizacionListResponse, OrganizacionMetrics, OrganizacionPatchRequest, OrganizacionResponse,
)
from app.schemas.auth import error_payload
from app.services import organizacion_service

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())


async def _detail(db, org) -> OrganizacionDetailResponse:
    metricas = await org_repo.metricas(db, org.id_organizaciones)
    return OrganizacionDetailResponse(
        id_organizaciones=org.id_organizaciones,
        nombre=org.nombre,
        slug=org.slug,
        creado_en=org.creado_en,
        metricas=OrganizacionMetrics(**metricas),
    )


@router.post("", response_model=OrganizacionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizacionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Usuario = Depends(require_admin_plataforma()),
):
    """Solo admin_plataforma. `correo_admin` opcional: crea el admin de la org + correo con credenciales."""
    try:
        result = await organizacion_service.create_org(
            db, body.nombre, body.slug, body.correo_admin, str(actor.id_usuarios),
            request.headers.get("x-request-id", ""),
        )
    except ValueError as e:
        msg = str(e)
        if "ya está en uso" in msg or "ya existe" in msg:
            _raise("DUPLICATE", msg, 409)
        _raise("VALIDATION_ERROR", msg, 422)
    org = result["org"]
    admin_payload = None
    if result["admin"] is not None:
        admin_payload = {
            "id_usuarios": result["admin"].id_usuarios,
            "correo": result["admin"].correo,
            "estado": result["admin"].estado,
            "contrasena_temporal_enviada": result["correo_enviado"],
        }
    return OrganizacionCreateResponse(
        organizacion=OrganizacionResponse(
            id_organizaciones=org.id_organizaciones, nombre=org.nombre, slug=org.slug, creado_en=org.creado_en
        ),
        admin=admin_payload,
    )


@router.get("", response_model=OrganizacionListResponse)
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    actor: Usuario = Depends(require_admin_plataforma()),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Listado de TODAS las organizaciones con sus métricas — solo admin_plataforma (decisión #7)."""
    total, orgs = await org_repo.list_all(db, limit, offset)
    items = [await _detail(db, o) for o in orgs]
    return OrganizacionListResponse(total=total, items=items, limit=limit, offset=offset)


@router.get("/{org_id}", response_model=OrganizacionDetailResponse)
async def get_organization(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Usuario = Depends(get_current_user),
):
    """admin_plataforma ve cualquiera; los demás SOLO su propia organización (org_id del JWT, §6.1)."""
    if actor.rol != "admin_plataforma" and actor.org_id != org_id:
        _raise("FORBIDDEN", "No puedes ver una organización que no es la tuya", 403)
    org = await org_repo.find_by_id(db, org_id)
    if org is None:
        _raise("NOT_FOUND", "Organización no encontrada", 404)
    return await _detail(db, org)


@router.patch("/{org_id}", response_model=OrganizacionResponse)
async def patch_organization(
    org_id: uuid.UUID,
    body: OrganizacionPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Edición solo por el admin_organizacion de ESA organización (rol del JWT)."""
    if user.rol != "admin_organizacion" or user.org_id != org_id:
        _raise("FORBIDDEN", "Solo el admin_organizacion de esta organización puede editarla", 403)
    org = await org_repo.find_by_id(db, org_id)
    if org is None:
        _raise("NOT_FOUND", "Organización no encontrada", 404)
    if body.nombre is None and body.slug is None:
        _raise("VALIDATION_ERROR", "Nada que editar: envía nombre y/o slug", 422)
    try:
        org = await organizacion_service.patch_org(
            db, org, body.nombre, body.slug, user, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        msg = str(e)
        if "ya está en uso" in msg:
            _raise("DUPLICATE", msg, 409)
        _raise("VALIDATION_ERROR", msg, 422)
    return OrganizacionResponse(id_organizaciones=org.id_organizaciones, nombre=org.nombre, slug=org.slug, creado_en=org.creado_en)
