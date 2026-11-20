import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.destinatario import Destinatario
from app.models.grupo import Grupo
from app.models.usuario import Usuario
from app.repositories import destinatario_repository as dest_repo
from app.repositories import grupo_repository as grupo_repo
from app.schemas.auth import error_payload
from app.schemas.destinatario import (
    CSVImportResponse, DestinatarioCreateRequest, DestinatarioDetailResponse, DestinatarioListResponse,
    DestinatarioPatchRequest, DestinatarioResponse, InstantaneaResponse,
)
from app.services import destinatario_service

router = APIRouter(prefix="/recipients", tags=["recipients"])

MAX_CSV_BYTES = 2 * 1024 * 1024

def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())

def _response(d: Destinatario) -> DestinatarioResponse:
    return DestinatarioResponse(
        id_destinatarios=d.id_destinatarios, correo=d.correo, grupo_id=d.grupo_id, activo=d.activo, creado_en=d.creado_en
    )

async def _grupo_en_org_o_404(db: AsyncSession, grupo_id: uuid.UUID, org_id: uuid.UUID) -> Grupo:
    grupo = await grupo_repo.find_by_id_in_org(db, grupo_id, org_id)
    if grupo is None:
        _raise("NOT_FOUND", "Grupo no encontrado", 404)
    return grupo

async def _destinatario_o_404(db: AsyncSession, destinatario_id: uuid.UUID, org_id: uuid.UUID) -> Destinatario:
    d = await dest_repo.find_by_id_in_org(db, destinatario_id, org_id)
    if d is None:
        _raise("NOT_FOUND", "Destinatario no encontrado", 404)
    return d

@router.post("", response_model=DestinatarioResponse, status_code=status.HTTP_201_CREATED)
async def create_recipient(
    body: DestinatarioCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Alta individual. El grupo debe existir en la organización (404 si no). Correo duplicado → 409."""
    grupo = await _grupo_en_org_o_404(db, body.grupo_id, org_id)
    try:
        d = await destinatario_service.create_destinatario(
            db, org_id, grupo, body.correo, actor, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        if "ya existe" in str(e):
            _raise("DUPLICATE", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return _response(d)

@router.post("/import", response_model=CSVImportResponse, status_code=status.HTTP_201_CREATED)
async def import_recipients(
    request: Request,
    file: UploadFile = File(..., description="CSV con encabezados 'correo,grupo' (grupo por nombre)"),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Importación masiva por CSV. Nunca falla por filas inválidas: las reporta con detalle."""
    datos = await file.read()
    if len(datos) > MAX_CSV_BYTES:
        _raise("VALIDATION_ERROR", "El archivo supera el máximo de 2 MB", 422)
    contenido = datos.decode("utf-8-sig", errors="replace")
    try:
        return CSVImportResponse(**await destinatario_service.import_csv(
            db, org_id, contenido, actor, request.headers.get("x-request-id", "")
        ))
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)

@router.get("", response_model=DestinatarioListResponse)
async def list_recipients(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    grupo_id: uuid.UUID | None = Query(default=None, description="Filtrar por grupo de la organización"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Destinatarios de la organización (activos e inactivos), filtro opcional por grupo."""
    if grupo_id is not None and await grupo_repo.find_by_id_in_org(db, grupo_id, org_id) is None:
        _raise("NOT_FOUND", "Grupo no encontrado", 404)
    total, items = await dest_repo.list_by_org(db, org_id, limit, offset, grupo_id)
    return DestinatarioListResponse(
        total=total, items=[_response(d) for d in items], limit=limit, offset=offset
    )

@router.get("/{destinatario_id}", response_model=DestinatarioDetailResponse)
async def get_recipient(
    destinatario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Detalle + histórico del índice de phishing (instantáneas, más reciente primero)."""
    d = await _destinatario_o_404(db, destinatario_id, org_id)
    historico = await dest_repo.historico_instantaneas(db, org_id, d.id_destinatarios)
    return DestinatarioDetailResponse(
        **_response(d).model_dump(),
        historico=[
            InstantaneaResponse(
                campana_id=i.campana_id, puntaje_phishing=float(i.puntaje_phishing), nivel=i.nivel, creado_en=i.creado_en
            )
            for i in historico
        ],
    )

@router.patch("/{destinatario_id}", response_model=DestinatarioResponse)
async def patch_recipient(
    destinatario_id: uuid.UUID,
    body: DestinatarioPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Edita correo y/o grupo. Ambos validados dentro de la organización."""
    d = await _destinatario_o_404(db, destinatario_id, org_id)
    grupo = None
    if body.grupo_id is not None:
        grupo = await _grupo_en_org_o_404(db, body.grupo_id, org_id)
    if body.correo is None and body.grupo_id is None:
        _raise("VALIDATION_ERROR", "Nada que editar: envía correo y/o grupo_id", 422)
    try:
        d = await destinatario_service.update_destinatario(
            db, d, body.correo, grupo, actor, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        if "ya existe" in str(e):
            _raise("DUPLICATE", str(e), 409)
        _raise("VALIDATION_ERROR", str(e), 422)
    return _response(d)

@router.patch("/{destinatario_id}/deactivate", response_model=DestinatarioResponse)
async def deactivate_recipient(
    destinatario_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Borrado lógico (decisión #9): conserva el registro y su histórico."""
    d = await _destinatario_o_404(db, destinatario_id, org_id)
    try:
        d = await destinatario_service.deactivate_destinatario(db, d, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _raise("VALIDATION_ERROR", str(e), 422)
    return _response(d)
