import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_org, require_roles
from app.models.usuario import Usuario
from app.repositories import campana_repository as campana_repo
from app.repositories import grupo_repository as grupo_repo
from app.repositories import usuario_repository as user_repo
from app.schemas.auth import error_payload
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])

FORMATOS = ("csv", "pdf")

def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())

def _respuesta(contenido: bytes, formato: str, nombre_archivo: str, media_type: str) -> Response:
    return Response(
        content=contenido,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}.{formato}"'},
    )

@router.get("/campaigns/{campana_id}/export")
async def export_campaign(
    campana_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    format: str = Query(default="pdf", pattern="^(csv|pdf)$"),
):
    """Reporte exportable de una campaña (§4.13): metadata + embudo + tabla por destinatario."""
    campana = await campana_repo.find_by_id_in_org(db, campana_id, org_id)
    if campana is None:
        _raise("NOT_FOUND", "Campaña no encontrada", 404)
    grupo = await grupo_repo.find_by_id_in_org(db, campana.grupo_id, org_id)
    embudo = await campana_repo.stats_embudo(db, campana.id_campanas)
    _, tabla = await campana_repo.tabla_destinatarios(db, campana.id_campanas, limit=100000, offset=0)

    meta: list[tuple[str, object]] = [
        ("Campaña", campana.nombre),
        ("Estado", campana.estado),
        ("Grupo", grupo.nombre if grupo else "-"),
        ("Expiración (horas)", campana.expiracion_horas),
        ("Creada", campana.creado_en),
        ("Iniciada", campana.iniciada_en),
        ("Finalizada", campana.finalizada_en),
    ]
    if format == "csv":
        contenido = report_service.csv_campana(meta, embudo, tabla)
        media = "text/csv; charset=utf-8"
    else:
        contenido = report_service.pdf_campana(meta, embudo, tabla)
        media = "application/pdf"

    await user_repo.save_audit(
        db, org_id, "report_exported",
        f"Reporte de campaña exportado ({format}): {campana.nombre}", actor_id=actor.id_usuarios,
    )
    await db.commit()
    nombre = report_service.slug(f"campana-{campana.nombre}")
    return _respuesta(contenido, format, nombre, media)

@router.get("/groups/{grupo_id}/export")
async def export_group(
    grupo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    actor: Usuario = Depends(require_roles("admin_organizacion", "analista")),
    format: str = Query(default="pdf", pattern="^(csv|pdf)$"),
):
    """Reporte de madurez de un grupo (§4.13): índice promedio + distribución + tabla por destinatario."""
    grupo = await grupo_repo.find_by_id_in_org(db, grupo_id, org_id)
    if grupo is None:
        _raise("NOT_FOUND", "Grupo no encontrado", 404)
    filas = await grupo_repo.filas_informe_grupo(db, org_id, grupo_id)
    indice = await grupo_repo.indice_promedio(db, org_id, grupo_id)
    activos = await grupo_repo.count_destinatarios_activos(db, grupo_id)

    distribucion = {nivel: 0 for nivel in report_service.NIVELES}
    for f in filas:
        if f["nivel"] in distribucion:
            distribucion[f["nivel"]] += 1

    meta: list[tuple[str, object]] = [
        ("Grupo", grupo.nombre),
        ("Perfil", grupo.perfil),
        ("Creada", grupo.creado_en),
        ("Destinatarios activos", activos),
        ("Índice promedio", None if indice is None else round(indice, 2)),
    ]
    if format == "csv":
        contenido = report_service.csv_grupo(meta, distribucion, filas)
        media = "text/csv; charset=utf-8"
    else:
        contenido = report_service.pdf_grupo(meta, distribucion, filas)
        media = "application/pdf"

    await user_repo.save_audit(
        db, org_id, "report_exported",
        f"Reporte de grupo exportado ({format}): {grupo.nombre}", actor_id=actor.id_usuarios,
    )
    await db.commit()
    nombre = report_service.slug(f"grupo-{grupo.nombre}")
    return _respuesta(contenido, format, nombre, media)
