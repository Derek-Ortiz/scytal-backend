import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log_event
from app.db.session import SessionLocal
from app.models.alerta import Alerta
from app.models.campana import Campana, DestinatarioCampana
from app.models.instantanea import InstantaneaPhishing
from app.models.usuario import Usuario
from app.repositories import campana_repository as campana_repo
from app.repositories import grupo_repository as grupo_repo
from app.repositories import plantilla_repository as plantilla_repo
from app.repositories import qr_zona_repository as qr_repo
from app.repositories import usuario_repository as user_repo
from app.services.email_service import send_many_detailed
from app.services.maturity_service import calcular_puntaje_phishing, nivel_phishing
from app.services.qr_service import generar_qr_base64

class EstadoInvalido(ValueError):
    """Transición/edición imposible por el estado actual → el router responde 409 CONFLICT."""

@dataclass
class PlanDespacho:
    """Datos para el envío en background del correo de campaña (tras responder el HTTP)."""

    items: list[tuple[uuid.UUID, str, str]] = field(default_factory=list)
    asunto: str = ""
    contenido_html: str = ""

ASUNTO_FEEDBACK = "Resultados de tu simulación de phishing"
ASUNTO_CORREO_DEFECTO = "Simulación de phishing de seguridad"

def render_correo(contenido_html: str, token: str, base_url: str) -> str:
    """Sustituye {{enlace}} y {{pixel}} en el HTML de la plantilla.

    - {{enlace}} → URL absoluta de /track/click con el token único del destinatario.
    - {{pixel}}  → img 1x1 de /track/open (registro de apertura).
    Si la plantilla no trae los marcadores, se AÑADEN al final: sin enlace la simulación no
    funciona y sin pixel no se mide apertura.
    """
    base = base_url.rstrip("/")
    enlace = f"{base}/track/click?t={token}"
    pixel = f'<img src="{base}/track/open?t={token}" width="1" height="1" alt="" style="display:none" />'
    html = contenido_html.replace("{{enlace}}", enlace).replace("{{pixel}}", pixel)
    if "{{enlace}}" not in contenido_html:
        html += f'<p><a href="{enlace}">Abrir el mensaje</a></p>'
    if "{{pixel}}" not in contenido_html:
        html += pixel
    return html

async def create_campana(
    db: AsyncSession, org_id: uuid.UUID, grupo_id: uuid.UUID, plantilla_id: uuid.UUID | None,
    nombre: str, expiracion_horas: int, actor: Usuario, request_id: str,
) -> Campana:
    if plantilla_id is not None:
        plantilla = await plantilla_repo.find_by_id_visible(db, plantilla_id, org_id)
        if plantilla is None:
            raise ValueError("la plantilla no existe o no es visible para tu organización")
    c = await campana_repo.create(db, org_id, grupo_id, plantilla_id, nombre, expiracion_horas)
    await user_repo.save_audit(
        db, org_id, "campaign_created", f"Campaña creada: {c.nombre} (pendiente, expira en {expiracion_horas} h)",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("campaign_created", request_id=request_id, campana_id=str(c.id_campanas), org_id=str(org_id))
    return c

async def update_campana(
    db: AsyncSession, campana: Campana,
    nombre: str | None, grupo_id: uuid.UUID | None, plantilla_id: uuid.UUID | None,
    expiracion_horas: int | None, actor: Usuario, request_id: str,
) -> Campana:
    if campana.estado == "activa":
        if nombre is not None or grupo_id is not None or plantilla_id is not None:
            raise EstadoInvalido("con la campaña activa solo se puede editar expiracion_horas")
        if expiracion_horas is None:
            raise ValueError("nada que editar: con la campaña activa solo se permite expiracion_horas")
        await campana_repo.re_datuar_tokens(db, campana.id_campanas, expiracion_horas)
        await qr_repo.re_datuar_tokens(db, campana.id_campanas, expiracion_horas)
        campana.expiracion_horas = expiracion_horas
        await user_repo.save_audit(
            db, campana.org_id, "campaign_expiry_updated",
            f"Expiración de campaña activa ajustada a {expiracion_horas} h (tokens re-daturados)",
            actor_id=actor.id_usuarios,
        )
        await db.commit()
        log_event("campaign_expiry_updated", request_id=request_id, campana_id=str(campana.id_campanas))
        return campana

    if campana.estado != "pendiente":
        raise EstadoInvalido(f"no se puede editar una campaña en estado {campana.estado}")

    if nombre is None and grupo_id is None and plantilla_id is None and expiracion_horas is None:
        raise ValueError("nada que editar: envía al menos un campo")
    if grupo_id is not None:
        if await grupo_repo.find_by_id_in_org(db, grupo_id, campana.org_id) is None:
            raise ValueError("el grupo no existe en tu organización")
    if plantilla_id is not None:
        if await plantilla_repo.find_by_id_visible(db, plantilla_id, campana.org_id) is None:
            raise ValueError("la plantilla no existe o no es visible para tu organización")
    c = await campana_repo.update_campos(
        db, campana, nombre=nombre, grupo_id=grupo_id, plantilla_id=plantilla_id, expiracion_horas=expiracion_horas,
    )
    await user_repo.save_audit(
        db, campana.org_id, "campaign_updated", f"Campaña editada: {c.nombre}", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("campaign_updated", request_id=request_id, campana_id=str(c.id_campanas))
    return c

async def definir_canales(
    db: AsyncSession, campana: Campana, canales: list[str], zonas: list[str] | None,
    actor: Usuario, request_id: str,
) -> Campana:
    """POST /channels: solo en pendiente (decisión). Reemplaza el set completo."""
    if campana.estado != "pendiente":
        raise EstadoInvalido("los canales solo se definen con la campaña pendiente")
    if "qr" in canales:
        if not zonas:
            raise ValueError("el canal 'qr' requiere al menos una zona")
        await qr_repo.replace_zonas(db, campana.id_campanas, zonas)
    else:
        await qr_repo.borrar_zonas(db, campana.id_campanas)
    await campana_repo.replace_canales(db, campana.id_campanas, canales)
    detalle = ", ".join(canales) + (f" (zonas: {', '.join(zonas)})" if zonas else "")
    await user_repo.save_audit(
        db, campana.org_id, "campaign_channels_set", f"Canales de '{campana.nombre}': {detalle}",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("campaign_channels_set", request_id=request_id, campana_id=str(campana.id_campanas), canales=canales)
    return campana

async def launch(
    db: AsyncSession, campana: Campana, expiracion_horas: int | None, actor: Usuario, request_id: str
) -> tuple[Campana, PlanDespacho | None, int]:
    """Pasa a activa y devuelve (campaña, plan de correos|None, nº zonas qr).

    El ROUTER agenda `despachar_correos_lanzamiento` como BackgroundTask: la respuesta HTTP
    no espera al SMTP. Valida prerequisitos → ValueError (422); estado imposible → EstadoInvalido (409).
    """
    if campana.estado == "activa":
        raise EstadoInvalido("la campaña ya está activa")
    if campana.estado == "programada":
        raise EstadoInvalido("la programación de campañas no está implementada")

    if campana.plantilla_id is None:
        raise ValueError("asigna una plantilla antes de lanzar: el QR y el correo necesitan su landing")
    canales = await campana_repo.get_canales(db, campana.id_campanas)
    if not canales:
        raise ValueError("define al menos un canal (correo/qr) antes de lanzar")
    zonas = await qr_repo.get_zonas(db, campana.id_campanas) if "qr" in canales else []
    if "qr" in canales and not zonas:
        raise ValueError("el canal 'qr' exige al menos una zona definida")
    plantilla = await plantilla_repo.find_by_id_visible(db, campana.plantilla_id, campana.org_id)
    if plantilla is None:
        raise ValueError("la plantilla asignada ya no existe o no es visible")
    destinatarios = await campana_repo.destinatarios_activos_del_grupo(db, campana.grupo_id)
    if not destinatarios:
        raise ValueError("el grupo no tiene destinatarios activos")

    horas = expiracion_horas or campana.expiracion_horas
    pares = await campana_repo.preparar_tokens(db, campana.id_campanas, destinatarios, horas)
    if zonas:
        await qr_repo.fijar_expiracion(db, campana.id_campanas, horas)
    campana.estado = "activa"
    campana.iniciada_en = datetime.now(timezone.utc)
    campana.expiracion_horas = horas
    await db.flush()

    correo_para_todos = "correo" in canales
    correo_de_plantilla = plantilla.asunto or ASUNTO_CORREO_DEFECTO
    plan = None
    if correo_para_todos:
        correos = {d.id_destinatarios: d.correo for d in destinatarios}
        plan = PlanDespacho(
            items=[(fila.id_destinatarios_campana, correos[fila.destinatario_id], token) for fila, token in pares],
            asunto=correo_de_plantilla,
            contenido_html=plantilla.contenido_html,
        )

    await user_repo.save_audit(
        db, campana.org_id, "campaign_launched",
        f"Campaña lanzada: {campana.nombre} ({len(pares)} destinatarios, canales {', '.join(canales)}, "
        f"expira en {horas} h)",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event(
        "campaign_launched", request_id=request_id, campana_id=str(campana.id_campanas),
        destinatarios=len(pares), zonas_qr=len(zonas),
    )
    return campana, plan, len(zonas)

async def _enviar_lote(lote: list[tuple[str, str, str, str | None]], *, request_id: str | None = None) -> list[bool]:
    """Punto único de envío: los tests lo reemplazan para no depender del SMTP."""
    return await send_many_detailed(lote, request_id=request_id)

async def despachar_correos_lanzamiento(plan: PlanDespacho, request_id: str | None = None) -> None:
    """BackgroundTask del launch: abre SU PROPIA sesión y estampa enviado_en por éxito individual.

    Un fallo de SMTP nunca rompe nada: el resto de correos sigue y los fallidos quedan sin
    enviado_en (visibles como 'pendiente' en la tabla de resultados).
    """
    if not plan.items:
        return
    base = get_settings().FRONTEND_BASE_URL.rstrip("/")
    lote: list[tuple[str, str, str, str | None]] = []
    for _fila_id, correo, token in plan.items:
        texto = (
            "Has sido seleccionada/o para una simulación de phishing de seguridad. "
            f"Ábrelo aquí: {base}/track/click?t={token}"
        )
        lote.append((correo, plan.asunto, texto, render_correo(plan.contenido_html, token, base)))
    resultados = await _enviar_lote(lote, request_id=request_id)
    ok_ids = [plan.items[i][0] for i, ok in enumerate(resultados) if ok]
    if ok_ids:
        async with SessionLocal() as db:
            await db.execute(
                update(DestinatarioCampana)
                .where(
                    DestinatarioCampana.id_destinatarios_campana.in_(ok_ids),
                    DestinatarioCampana.enviado_en.is_(None),
                )
                .values(enviado_en=func.now())
            )
            await db.commit()
    log_event(
        "campaign_emails_dispatched", request_id=request_id,
        ok=len(ok_ids), fallos=len(resultados) - len(ok_ids),
    )

async def cancel(db: AsyncSession, campana: Campana, actor: Usuario, request_id: str) -> Campana:
    if campana.estado not in ("pendiente", "activa"):
        raise EstadoInvalido(f"no se puede cancelar una campaña en estado {campana.estado}")
    await campana_repo.caducar_tokens(db, campana.id_campanas)
    await qr_repo.caducar_tokens(db, campana.id_campanas)
    c = await campana_repo.set_estado(db, campana, "cancelada")
    await user_repo.save_audit(
        db, campana.org_id, "campaign_cancelled",
        f"Campaña cancelada: {c.nombre} (tokens invalidados al instante)", actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("campaign_cancelled", request_id=request_id, campana_id=str(c.id_campanas))
    return c

async def finish(db: AsyncSession, campana: Campana, actor: Usuario, request_id: str) -> dict:
    """Solo desde activa → completada. Calcula el índice §7 por token de destinatario.

    - abrió = abierto_en marcado; clicó = clic_en marcado; envió = EXISTS eventos_tracking 'subido'
      (el contenido del formulario falso NUNCA se guarda, §7).
    - QR: sus clics son anónimos y no generan instantánea.
    - Alertas: 1 por destinatario que envió datos (tipo riesgo_phishing, referencia destinatario).
    """
    if campana.estado != "activa":
        raise EstadoInvalido(f"solo se puede finalizar una campaña activa (estado actual: {campana.estado})")

    filas = await campana_repo.filas_para_finalizar(db, campana.id_campanas)
    instantaneas: list[InstantaneaPhishing] = []
    remitentes: list[uuid.UUID] = []
    for f in filas:
        puntaje = calcular_puntaje_phishing(
            abrio=f["abierto_en"] is not None, clico=f["clic_en"] is not None, envio=bool(f["envio"])
        )
        nivel = nivel_phishing(puntaje)
        instantaneas.append(InstantaneaPhishing(
            org_id=campana.org_id, destinatario_id=f["destinatario_id"],
            campana_id=campana.id_campanas, puntaje_phishing=puntaje, nivel=nivel,
        ))
        if f["envio"]:
            remitentes.append(f["destinatario_id"])
    if instantaneas:
        db.add_all(instantaneas)
    alertas = [Alerta(
        org_id=campana.org_id, tipo="riesgo_phishing",
        referencia_tipo="destinatario", referencia_id=d,
    ) for d in remitentes]
    if alertas:
        db.add_all(alertas)

    campana.estado = "completada"
    campana.finalizada_en = datetime.now(timezone.utc)
    await db.flush()
    await user_repo.save_audit(
        db, campana.org_id, "campaign_finished",
        f"Campaña finalizada: {campana.nombre} ({len(instantaneas)} instantáneas, {len(alertas)} alertas)",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event(
        "campaign_finished", request_id=request_id, campana_id=str(campana.id_campanas),
        instantaneas=len(instantaneas), alertas=len(alertas),
    )
    return {"instantaneas": len(instantaneas), "alertas": len(alertas)}

def _correo_feedback(puntaje: float, nivel: str, base_url: str) -> tuple[str, str]:
    texto = (
        f"En la simulación de phishing reciente tu índice de resistencia fue "
        f"{puntaje:.0f}/100 (nivel {nivel}). Revisa las recomendaciones para mejorar tu detección."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">'
        '<h2 style="color:#0d3b66;">Resultados de tu simulación de phishing</h2>'
        f'<p>Tu índice de resistencia fue <strong>{puntaje:.0f}/100</strong> '
        f'(nivel <strong>{nivel}</strong>).</p>'
        '<ul>'
        '<li>Verifica siempre el remitente y el dominio real del enlace.</li>'
        '<li>Ante la duda, entra al servicio escribiendo su dirección oficial, no desde el correo.</li>'
        '<li>Reporta correos sospechosos a tu área de TI.</li>'
        '</ul>'
        '<p style="color:#58151c;background:#f8d7da;padding:10px;">PÁGINA DE PRUEBA — '
        'este mensaje es parte de una simulación educativa de Scytal.</p>'
        f'<p style="font-size:11px;color:#666;">Scytal · {base_url}</p>'
        '</div>'
    )
    return texto, html

async def enviar_feedback(db: AsyncSession, campana: Campana, actor: Usuario, request_id: str) -> list[tuple[str, str, str, str | None]]:
    """Marca feedback_enviado_en DE INMEDIATO (bloquea el doble envío → 409) y retorna el lote
    pre-renderizado para el BackgroundTask `despachar_correos_feedback`."""
    if campana.estado != "completada":
        raise EstadoInvalido("solo se puede enviar feedback de una campaña completada")
    if campana.feedback_enviado_en is not None:
        raise EstadoInvalido("el feedback de esta campaña ya fue enviado")

    base = get_settings().FRONTEND_BASE_URL.rstrip("/")
    resultados = await campana_repo.resultados_para_feedback(db, campana.id_campanas)
    lote = []
    for r in resultados:
        texto, html = _correo_feedback(r["puntaje"], r["nivel"], base)
        lote.append((r["correo"], ASUNTO_FEEDBACK, texto, html))
    campana.feedback_enviado_en = datetime.now(timezone.utc)
    await db.flush()
    await user_repo.save_audit(
        db, campana.org_id, "campaign_feedback_sent",
        f"Feedback de '{campana.nombre}' programado para {len(lote)} destinatarios",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("campaign_feedback_sent", request_id=request_id, campana_id=str(campana.id_campanas), correos=len(lote))
    return lote

async def despachar_correos_feedback(lote: list[tuple[str, str, str, str | None]], request_id: str | None = None) -> None:
    if not lote:
        return
    resultados = await _enviar_lote(lote, request_id=request_id)
    log_event("campaign_feedback_dispatched", request_id=request_id,
              ok=sum(1 for r in resultados if r), fallos=sum(1 for r in resultados if not r))

async def urls_qr(db: AsyncSession, campana: Campana) -> list[dict]:
    """[{zona, url, qr_base64}] renderizado al vuelo (GET /campaigns/{id}/qr)."""
    zonas = await qr_repo.get_zonas(db, campana.id_campanas)
    base = get_settings().FRONTEND_BASE_URL.rstrip("/")
    out = []
    for z in zonas:
        url = f"{base}/track/click?t={z.token_qr}"
        out.append({"zona": z.zona, "url": url, "qr_base64": generar_qr_base64(url)})
    return out
