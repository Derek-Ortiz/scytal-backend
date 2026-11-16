"""Rutas /groups (§4.5). Aislamiento multi-tenant: org_id solo del JWT (§6.1).

Lecturas: admin_organizacion y analista. Escrituras: solo admin_organizacion.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.grupo import Grupo
from app.models.usuario import Usuario
from app.repositories import grupo_repository as grupo_repo
from app.schemas.auth import error_payload
from app.schemas.grupo import (
    GrupoCreateRequest, GrupoDetailResponse, GrupoListResponse, GrupoMetrics, GrupoPatchRequest, GrupoResponse,
)
from app.services import grupo_service

router = APIRouter(prefix="/groups", tags=["groups"])


def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())


async def _detail(db: AsyncSession, grupo: Grupo) -> GrupoDetailResponse:
    return GrupoDetailResponse(
        id_grupos=grupo.id_grupos,
        nombre=grupo.nombre,
        perfil=grupo.perfil,
        creado_en=grupo.creado_en,
        metricas=GrupoMetrics(
            destinatarios_activos=await grupo_repo.count_destinatarios_activos(db, grupo.id_grupos),
            indice_promedio=await grupo_repo.indice_promedio(db, grupo.org_id, grupo.id_grupos),
        ),
    )


async def _grupo_o_404(db: AsyncSession, grupo_id: uuid.UUID, org_id: uuid.UUID) -> Grupo:
    grupo = await grupo_repo.find_by_id_in_org(db, grupo_id, org_id)
    if grupo is None:
        # Nunca se revela si existe en otra organización (§6.1)
        _raise("NOT_FOUND", "Grupo no encontrado", 404)
    return grupo


@router.post("", response_model=GrupoDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GrupoCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Crea un grupo en la propia organización. Nombre duplicado (case-insensitive) → 409."""
    try:
        grupo = await grupo_service.create_grupo(
            db, org_id, body.nombre, body.perfil, actor, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        if "ya existe" in str(e):
            _raise("DUPLICATE", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return await _detail(db, grupo)


@router.get("", response_model=GrupoListResponse)
async def list_groups(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Grupos de la organización con métricas por grupo (destinatarios activos + índice promedio)."""
    total, grupos = await grupo_repo.list_by_org(db, org_id, limit, offset)
    conteos, promedios = await grupo_repo.grupos_con_informe(db, org_id)
    items = [
        GrupoDetailResponse(
            id_grupos=g.id_grupos,
            nombre=g.nombre,
            perfil=g.perfil,
            creado_en=g.creado_en,
            metricas=GrupoMetrics(
                destinatarios_activos=conteos.get(g.id_grupos, 0),
                indice_promedio=promedios.get(g.id_grupos),
            ),
        )
        for g in grupos
    ]
    return GrupoListResponse(total=total, items=items, limit=limit, offset=offset)


@router.get("/{grupo_id}", response_model=GrupoDetailResponse)
async def get_group(
    grupo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    grupo = await _grupo_o_404(db, grupo_id, org_id)
    return await _detail(db, grupo)


@router.patch("/{grupo_id}", response_model=GrupoDetailResponse)
async def patch_group(
    grupo_id: uuid.UUID,
    body: GrupoPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    grupo = await _grupo_o_404(db, grupo_id, org_id)
    if body.nombre is None and body.perfil is None:
        _raise("VALIDATION_ERROR", "Nada que editar: envía nombre y/o perfil", 422)
    try:
        grupo = await grupo_service.update_grupo(
            db, grupo, body.nombre, body.perfil, actor, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        if "ya existe" in str(e):
            _raise("DUPLICATE", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return await _detail(db, grupo)


@router.delete("/{grupo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    grupo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Elimina el grupo. 409 si tiene campañas asociadas (RESTRICT); los destinatarios se borran en cascada."""
    grupo = await _grupo_o_404(db, grupo_id, org_id)
    try:
        await grupo_service.delete_grupo(db, grupo, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        if "campañas" in str(e):
            _raise("CONFLICT", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return None
