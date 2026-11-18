"""Rutas /templates (§4.7). Plantillas globales (org_id NULL) son de solo lectura para las orgs.

Lecturas: admin_organizacion y analista. Escrituras: solo admin_organizacion, y SOLO sobre
plantillas propias (global ajena → 403 FORBIDDEN).
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.plantilla import Plantilla
from app.models.usuario import Usuario
from app.repositories import plantilla_repository as plantilla_repo
from app.schemas.auth import error_payload
from app.schemas.plantilla import (
    PlantillaCreateRequest, PlantillaDetailResponse, PlantillaImportarRequest, PlantillaListResponse,
    PlantillaPatchRequest, PlantillaPreviewResponse,
)
from app.routers.previsualizar import MINUTOS_ENLACE_PREVIA
from app.core.security import create_preview_token
from app.services import clonador_service
from app.services import plantilla_service

router = APIRouter(prefix="/templates", tags=["templates"])


def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())


def _a_detalle(p: Plantilla, en_uso: bool) -> PlantillaDetailResponse:
    return PlantillaDetailResponse(
        id_plantillas=p.id_plantillas,
        org_id=p.org_id,
        nombre=p.nombre,
        perfil=p.perfil,
        canal=p.canal,
        asunto=p.asunto,
        contenido_html=p.contenido_html,
        landing_html=p.landing_html,
        creado_en=p.creado_en,
        actualizado_en=p.actualizado_en,
        en_uso=en_uso,
    )


async def _visible_o_404(db: AsyncSession, plantilla_id: uuid.UUID, org_id: uuid.UUID) -> Plantilla:
    p = await plantilla_repo.find_by_id_visible(db, plantilla_id, org_id)
    if p is None:
        # Nunca se revela si existe en otra organización (§6.1)
        _raise("NOT_FOUND", "Plantilla no encontrada", 404)
    return p


@router.get("", response_model=PlantillaListResponse)
async def list_templates(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    perfil: str | None = Query(default=None, max_length=100),
    canal: Literal["correo", "qr"] | None = Query(default=None),
):
    """Globales + propias, filtrables por perfil/canal (§4.7)."""
    total, plantillas = await plantilla_repo.list_visible(db, org_id, limit, offset, perfil=perfil, canal=canal)
    items = []
    for p in plantillas:
        # en_uso por ítem: consulta puntual (listas de plantillas son cortas)
        items.append(_a_detalle(p, await plantilla_repo.en_uso(db, p.id_plantillas)))
    return PlantillaListResponse(total=total, items=items, limit=limit, offset=offset)


@router.post("", response_model=PlantillaDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: PlantillaCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    try:
        p = await plantilla_service.create_plantilla(
            db, org_id, body.nombre, body.perfil, body.canal, body.asunto,
            body.contenido_html, body.landing_html, actor, request.headers.get("x-request-id", ""),
        )
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)
    return _a_detalle(p, False)


@router.post("/importar", response_model=PlantillaDetailResponse, status_code=status.HTTP_201_CREATED)
async def import_template(
    body: PlantillaImportarRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Clona una página real por URL como plantilla propia (decisión A+B).

    Opción A: descarga estática (guardas SSRF). Si el HTML es una carcasa SPA vacía →
    Opción B: render con Chromium headless (Playwright). El snapshot queda congelado:
    scripts fuera, todos los formularios → /track/submit, leyenda obligatoria.
    """
    try:
        p = await clonador_service.importar_url(
            db, org_id, body.url, body.nombre, body.perfil, body.canal, body.asunto,
            actor, request.headers.get("x-request-id", ""),
        )
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)
    return _a_detalle(p, False)


@router.get("/{plantilla_id}/previsualizar", response_model=PlantillaPreviewResponse)
async def preview_template(
    plantilla_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Enlace efímero (JWT 30 min) que sirve la landing EXACTA que verá el destinatario.

    Útil para probar el clon en un navegador real (sin el frontend). El token solo abre
    ESTA plantilla y expira; el HTML ya viene sin scripts y con el CSS inlineado.
    """
    p = await _visible_o_404(db, plantilla_id, org_id)
    token = create_preview_token(str(p.id_plantillas), str(org_id), minutos=MINUTOS_ENLACE_PREVIA)
    base = str(request.base_url).rstrip("/")
    return PlantillaPreviewResponse(
        url=f"{base}/previsualizar/{token}", expira_en_minutos=MINUTOS_ENLACE_PREVIA,
    )


@router.get("/{plantilla_id}", response_model=PlantillaDetailResponse)
async def get_template(
    plantilla_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Detalle con preview (HTML completo) y bandera en_uso."""
    p = await _visible_o_404(db, plantilla_id, org_id)
    return _a_detalle(p, await plantilla_repo.en_uso(db, p.id_plantillas))


@router.patch("/{plantilla_id}", response_model=PlantillaDetailResponse)
async def patch_template(
    plantilla_id: uuid.UUID,
    body: PlantillaPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    p = await _visible_o_404(db, plantilla_id, org_id)
    if p.org_id != org_id:
        # Plantilla GLOBAL: legible por todos, editable solo por su dueña (aquí: ninguna org)
        _raise("FORBIDDEN", "Las plantillas globales no se pueden editar desde una organización", 403)
    if all(v is None for v in (body.nombre, body.perfil, body.canal, body.asunto, body.contenido_html, body.landing_html)):
        _raise("VALIDATION_ERROR", "Nada que editar: envía al menos un campo", 422)
    try:
        p = await plantilla_service.update_plantilla(
            db, p, body.nombre, body.perfil, body.canal, body.asunto,
            body.contenido_html, body.landing_html, actor, request.headers.get("x-request-id", ""),
        )
    except PermissionError as e:
        _raise("FORBIDDEN", str(e), 403)
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)
    return _a_detalle(p, await plantilla_repo.en_uso(db, p.id_plantillas))


@router.delete("/{plantilla_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    plantilla_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """DELETE solo si no hay campaña pendiente/programada/activa que la use (→ 409)."""
    p = await _visible_o_404(db, plantilla_id, org_id)
    if p.org_id != org_id:
        _raise("FORBIDDEN", "Las plantillas globales no se pueden eliminar desde una organización", 403)
    try:
        await plantilla_service.delete_plantilla(db, p, actor, request.headers.get("x-request-id", ""))
    except PermissionError as e:
        _raise("FORBIDDEN", str(e), 403)
    except ValueError as e:
        if "en uso" in str(e):
            _raise("CONFLICT", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return None
