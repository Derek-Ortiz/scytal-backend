"""Rutas /campaigns (§4.8) — 11 rutas del spec + extensión GET /{id}/qr (render de zonas).

Lecturas (list/detail/stats/recipients/qr): admin_organizacion y analista.
Escrituras (create/patch/channels/launch/finish/send-feedback/cancel): solo admin_organizacion.
El envío de correos (launch/feedback) va en BackgroundTasks: la respuesta no espera al SMTP.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.campana import Campana
from app.models.usuario import Usuario
from app.repositories import campana_repository as campana_repo
from app.schemas.auth import error_payload
from app.schemas.campana import (
    CampanaCanalResponse, CampanaChannelsRequest, CampanaCreateRequest, CampanaDetailResponse,
    CampanaFeedbackResponse, CampanaFinishResponse, CampanaLaunchRequest, CampanaLaunchResponse,
    CampanaListResponse, CampanaPatchRequest, CampanaQrResponse, CampanaRecipientsResponse,
    CampanaRecipienteRow, CampanaStatsResponse, QrZonaUrlResponse,
)
from app.services import campana_service
from app.services.campana_service import EstadoInvalido

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

ESTADOS = ("pendiente", "programada", "activa", "completada", "cancelada")


def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())


def _map_error(e: Exception):
    if isinstance(e, EstadoInvalido):
        _raise("CONFLICT", str(e), 409)
    _raise("VALIDATION_ERROR", str(e), 422)


async def _a_detalle(db: AsyncSession, c: Campana) -> CampanaDetailResponse:
    """Detalle con canales y nombres de zona (2 viajes, sin N+1)."""
    cid = c.id_campanas
    canales_map = await campana_repo.canales_de_campanas(db, [cid])
    zonas_map = await campana_repo.zonas_de_campanas(db, [cid])
    canales = [
        CampanaCanalResponse(canal=canal, zonas=zonas_map.get(cid, []) if canal == "qr" else [])
        for canal in sorted(canales_map.get(cid, []))
    ]
    return CampanaDetailResponse(
        id_campanas=cid,
        org_id=c.org_id,
        grupo_id=c.grupo_id,
        plantilla_id=c.plantilla_id,
        nombre=c.nombre,
        estado=c.estado,
        expiracion_horas=c.expiracion_horas,
        programada_en=c.programada_en,
        iniciada_en=c.iniciada_en,
        finalizada_en=c.finalizada_en,
        feedback_enviado_en=c.feedback_enviado_en,
        creado_en=c.creado_en,
        actualizado_en=c.actualizado_en,
        canales=canales,
    )


async def _campana_o_404(db: AsyncSession, campana_id: uuid.UUID, org_id: uuid.UUID) -> Campana:
    c = await campana_repo.find_by_id_in_org(db, campana_id, org_id)
    if c is None:
        # Nunca se revela si existe en otra organización (§6.1)
        _raise("NOT_FOUND", "Campaña no encontrada", 404)
    return c


@router.get("", response_model=CampanaListResponse)
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    estado: Literal["pendiente", "programada", "activa", "completada", "cancelada"] | None = Query(default=None),
    grupo_id: uuid.UUID | None = Query(default=None),
):
    """Listado de la org, filtrable por estado/grupo (§4.8)."""
    total, campanas = await campana_repo.list_by_org(db, org_id, limit, offset, estado=estado, grupo_id=grupo_id)
    ids = [c.id_campanas for c in campanas]
    canales_map = await campana_repo.canales_de_campanas(db, ids)
    zonas_map = await campana_repo.zonas_de_campanas(db, ids)
    items = []
    for c in campanas:
        canales = [
            CampanaCanalResponse(canal=canal, zonas=zonas_map.get(c.id_campanas, []) if canal == "qr" else [])
            for canal in sorted(canales_map.get(c.id_campanas, []))
        ]
        items.append(CampanaDetailResponse(
            id_campanas=c.id_campanas,
            org_id=c.org_id,
            grupo_id=c.grupo_id,
            plantilla_id=c.plantilla_id,
            nombre=c.nombre,
            estado=c.estado,
            expiracion_horas=c.expiracion_horas,
            programada_en=c.programada_en,
            iniciada_en=c.iniciada_en,
            finalizada_en=c.finalizada_en,
            feedback_enviado_en=c.feedback_enviado_en,
            creado_en=c.creado_en,
            actualizado_en=c.actualizado_en,
            canales=canales,
        ))
    return CampanaListResponse(total=total, items=items, limit=limit, offset=offset)


@router.post("", response_model=CampanaDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampanaCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Crea la campaña en estado `pendiente` (el "draft" del spec)."""
    try:
        c = await campana_service.create_campana(
            db, org_id, body.grupo_id, body.plantilla_id, body.nombre, body.expiracion_horas,
            actor, request.headers.get("x-request-id", ""),
        )
    except ValueError as e:
        _map_error(e)
    return await _a_detalle(db, c)


@router.get("/{campana_id}", response_model=CampanaDetailResponse)
async def get_campaign(
    campana_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    c = await _campana_o_404(db, campana_id, org_id)
    return await _a_detalle(db, c)


@router.patch("/{campana_id}", response_model=CampanaDetailResponse)
async def patch_campaign(
    campana_id: uuid.UUID,
    body: CampanaPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """`pendiente`: todo editable. `activa`: SOLO expiracion_horas (re-datura tokens). Resto → 409."""
    c = await _campana_o_404(db, campana_id, org_id)
    try:
        c = await campana_service.update_campana(
            db, c, body.nombre, body.grupo_id, body.plantilla_id, body.expiracion_horas,
            actor, request.headers.get("x-request-id", ""),
        )
    except ValueError as e:
        _map_error(e)
    return await _a_detalle(db, c)


@router.post("/{campana_id}/channels", response_model=CampanaDetailResponse)
async def set_channels(
    campana_id: uuid.UUID,
    body: CampanaChannelsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Define canales en `campana_canales` (reemplaza el set). Solo en `pendiente`; qr exige zonas."""
    c = await _campana_o_404(db, campana_id, org_id)
    try:
        c = await campana_service.definir_canales(
            db, c, body.canales, body.zonas, actor, request.headers.get("x-request-id", "")
        )
    except ValueError as e:
        _map_error(e)
    return await _a_detalle(db, c)


@router.post("/{campana_id}/launch", response_model=CampanaLaunchResponse)
async def launch_campaign(
    campana_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    body: CampanaLaunchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Pasa a `activa`: genera/regenera tokens y agenda el envío de correos en background."""
    c = await _campana_o_404(db, campana_id, org_id)
    request_id = request.headers.get("x-request-id", "")
    try:
        c, plan, nzonas = await campana_service.launch(
            db, c, body.expiracion_horas if body else None, actor, request_id
        )
    except ValueError as e:
        _map_error(e)
    if plan:
        background_tasks.add_task(campana_service.despachar_correos_lanzamiento, plan, request_id)
    return CampanaLaunchResponse(
        campana=await _a_detalle(db, c),
        emails_programados=len(plan.items) if plan else 0,
        zonas_qr=nzonas,
    )


@router.get("/{campana_id}/qr", response_model=CampanaQrResponse)
async def get_campaign_qr(
    campana_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Extensión: render de las zonas QR al vuelo (PNG base64 + URL pública del token de zona)."""
    c = await _campana_o_404(db, campana_id, org_id)
    zonas = await campana_service.urls_qr(db, c)
    if not zonas:
        _raise("NOT_FOUND", "La campaña no tiene zonas QR definidas", 404)
    return CampanaQrResponse(campana_id=c.id_campanas, zonas=[QrZonaUrlResponse(**z) for z in zonas])


@router.get("/{campana_id}/stats", response_model=CampanaStatsResponse)
async def get_campaign_stats(
    campana_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
):
    """Embudo: enviados/abiertos/clics/enviados-datos; los clics QR van aparte (anónimos)."""
    c = await _campana_o_404(db, campana_id, org_id)
    stats = await campana_repo.stats_embudo(db, c.id_campanas)
    return CampanaStatsResponse(
        campana_id=c.id_campanas, estado=c.estado, total_destinatarios=stats["total"],
        enviados=stats["enviados"], abiertos=stats["abiertos"], clics=stats["clics"],
        subidos=stats["subidos"], qr_clics=stats["qr_clics"],
    )


@router.get("/{campana_id}/recipients", response_model=CampanaRecipientsResponse)
async def get_campaign_recipients(
    campana_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Tabla de resultados por destinatario (envío/interacciones + índice al finalizar)."""
    c = await _campana_o_404(db, campana_id, org_id)
    total, filas = await campana_repo.tabla_destinatarios(db, c.id_campanas, limit, offset)
    return CampanaRecipientsResponse(
        campana_id=c.id_campanas, total=total,
        items=[CampanaRecipienteRow(**f) for f in filas],
        limit=limit, offset=offset,
    )


@router.post("/{campana_id}/finish", response_model=CampanaFinishResponse)
async def finish_campaign(
    campana_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Solo desde `activa` → `completada`: instantáneas 25/25/50 + alerta por cada envío de datos."""
    c = await _campana_o_404(db, campana_id, org_id)
    try:
        resumen = await campana_service.finish(db, c, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _map_error(e)
    return CampanaFinishResponse(campana=await _a_detalle(db, c), **resumen)


@router.post("/{campana_id}/send-feedback", response_model=CampanaFeedbackResponse)
async def send_feedback(
    campana_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """Solo desde `completada`, UNA sola vez (2ª → 409). El envío real va en background."""
    c = await _campana_o_404(db, campana_id, org_id)
    try:
        lote = await campana_service.enviar_feedback(db, c, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _map_error(e)
    background_tasks.add_task(campana_service.despachar_correos_feedback, lote, request.headers.get("x-request-id", ""))
    return CampanaFeedbackResponse(
        message="Feedback en cola de envío", emails_programados=len(lote),
    )


@router.post("/{campana_id}/cancel", response_model=CampanaDetailResponse)
async def cancel_campaign(
    campana_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion")),
):
    """`pendiente`/`activa` → `cancelada`; los tokens mueren AL INSTANTE (expira_en = ahora)."""
    c = await _campana_o_404(db, campana_id, org_id)
    try:
        c = await campana_service.cancel(db, c, actor, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _map_error(e)
    return await _a_detalle(db, c)
