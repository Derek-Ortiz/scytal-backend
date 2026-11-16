"""Lógica de negocio de /recipients (§4.6), incluida la importación por CSV.

CSV (decisión de diseño, documentada en prompt_frontend.md):
- Encabezados obligatorios en la primera línea: `correo,grupo` (grupo por NOMBRE, debe existir en la organización).
- Correo validado con el mismo regex estricto de /auth (CORREO_RE).
- Dedupe dentro del archivo y contra la organización (activos e inactivos: uk_destinatarios_org_correo).
- Filas inválidas se reportan con número de línea (máx 100 en el detalle).
- Borrado lógico (decisión #9): desactivar conserva el registro y su histórico.
"""
import csv
import io
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.models.destinatario import Destinatario
from app.models.grupo import Grupo
from app.models.usuario import Usuario
from app.repositories import destinatario_repository as dest_repo
from app.repositories import usuario_repository as user_repo
from app.schemas.auth import CORREO_RE

MAX_FILAS_CSV = 5000          # guarda anti-DoS: un CSV enorme no puede bloquear el worker
MAX_ERRORES_REPORTE = 100     # detalle de errores que se devuelve al cliente


@dataclass
class CSVParseResult:
    """Resultado del parseo puro del CSV (sin BD)."""
    validos: list[tuple[str, uuid.UUID]] = field(default_factory=list)   # (correo_min, grupo_id)
    errores: list[str] = field(default_factory=list)
    total_filas: int = 0
    invalidos: int = 0
    duplicados_in_file: int = 0


def parse_csv_import(contenido: str, grupos: dict[str, uuid.UUID]) -> CSVParseResult:
    """Parseo y validación PURA del CSV — sin BD, para pruebas unitarias.

    grupos: {nombre_minúsculas: id_grupos} de la organización.
    Lanza ValueError si el encabezado no es `correo,grupo` (el router responde 422).
    """
    resultado = CSVParseResult()
    lector = csv.reader(io.StringIO(contenido))

    filas = [f for f in lector]
    while filas and not any(c.strip() for c in filas[-1]):
        filas.pop()  # quita líneas vacías al final

    if not filas:
        raise ValueError("el archivo está vacío: se esperaba el encabezado 'correo,grupo'")

    encabezado = [c.strip().lower().lstrip("\ufeff") for c in filas[0]]
    if encabezado != ["correo", "grupo"]:
        raise ValueError("encabezados inválidos: la primera línea debe ser exactamente 'correo,grupo'")

    vistos: set[str] = set()
    for i, fila in enumerate(filas[1:], start=2):
        if not any(c.strip() for c in fila):
            continue  # línea vacía intermedia: se ignora
        resultado.total_filas += 1
        if resultado.total_filas > MAX_FILAS_CSV:
            raise ValueError(f"demasiadas filas: el máximo es {MAX_FILAS_CSV}")

        if len(fila) < 2:
            resultado.invalidos += 1
            _agregar(resultado, f"fila {i}: se esperaban 2 columnas (correo,grupo)")
            continue
        correo, grupo_nombre = fila[0].strip(), fila[1].strip()

        if len(correo) > 254 or not CORREO_RE.fullmatch(correo):
            resultado.invalidos += 1
            _agregar(resultado, f"fila {i}: correo no válido '{correo[:60]}'")
            continue
        grupo_id = grupos.get(grupo_nombre.lower())
        if grupo_id is None:
            resultado.invalidos += 1
            _agregar(resultado, f"fila {i}: el grupo '{grupo_nombre[:60]}' no existe en tu organización")
            continue

        correo_norm = correo.lower()
        if correo_norm in vistos:
            resultado.duplicados_in_file += 1
            _agregar(resultado, f"fila {i}: '{correo_norm}' duplicado dentro del archivo")
            continue
        vistos.add(correo_norm)
        resultado.validos.append((correo_norm, grupo_id))

    return resultado


def _agregar(resultado: CSVParseResult, detalle: str) -> None:
    if len(resultado.errores) < MAX_ERRORES_REPORTE:
        resultado.errores.append(detalle)


async def import_csv(
    db: AsyncSession, org_id: uuid.UUID, contenido: str, actor: Usuario, request_id: str
) -> dict:
    """Importa destinatarios desde el CSV. Persiste en una sola transacción. Retorna dict para CSVImportResponse."""
    grupos = await dest_repo.grupos_por_nombre(db, org_id)
    parseo = parse_csv_import(contenido, grupos)

    # Dedupe contra la org (activos e inactivos)
    correos_validos = [c for c, _ in parseo.validos]
    existentes = await dest_repo.correos_existentes(db, org_id, correos_validos)

    nuevos: list[Destinatario] = []
    duplicados = parseo.duplicados_in_file
    for correo, grupo_id in parseo.validos:
        if correo in existentes:
            duplicados += 1
            _agregar(parseo, f"'{correo}' ya existe en tu organización")
            continue
        nuevos.append(Destinatario(org_id=org_id, grupo_id=grupo_id, correo=correo))

    creados = len(nuevos)
    if nuevos:
        db.add_all(nuevos)
    await user_repo.save_audit(
        db, org_id, "recipients_imported",
        f"Importación CSV: {creados} creados, {duplicados} duplicados, {parseo.invalidos} inválidos",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event(
        "recipients_imported", request_id=request_id,
        creados=creados, duplicados=duplicados, invalidos=parseo.invalidos,
    )
    return {
        "total_filas": parseo.total_filas,
        "creados": creados,
        "duplicados": duplicados,
        "invalidos": parseo.invalidos,
        "errores": parseo.errores,
    }


async def create_destinatario(
    db: AsyncSession, org_id: uuid.UUID, grupo: Grupo, correo: str, actor: Usuario, request_id: str
) -> Destinatario:
    """Alta individual. `grupo` ya viene verificado en-org (router)."""
    if await dest_repo.find_by_correo(db, org_id, correo):
        raise ValueError("ya existe un destinatario con ese correo en tu organización")
    d = await dest_repo.create(db, org_id, grupo.id_grupos, correo)
    await user_repo.save_audit(
        db, org_id, "recipient_created", f"Destinatario creado: {d.correo} (grupo {grupo.nombre})", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("recipient_created", request_id=request_id, destinatario_id=str(d.id_destinatarios))
    return d


async def update_destinatario(
    db: AsyncSession,
    d: Destinatario,
    correo: str | None,
    grupo: Grupo | None,
    actor: Usuario,
    request_id: str,
) -> Destinatario:
    """Edición de correo y/o grupo. `grupo` ya viene verificado en-org (router)."""
    if correo is not None and correo.lower() != d.correo.lower():
        if await dest_repo.find_by_correo(db, d.org_id, correo):
            raise ValueError("ya existe un destinatario con ese correo en tu organización")
    d = await dest_repo.update(db, d, correo=correo, grupo_id=grupo.id_grupos if grupo else None)
    await user_repo.save_audit(
        db, d.org_id, "recipient_updated", f"Destinatario editado: {d.correo}", actor_id=actor.id_usuarios
    )
    await db.commit()
    log_event("recipient_updated", request_id=request_id, destinatario_id=str(d.id_destinatarios))
    return d


async def deactivate_destinatario(db: AsyncSession, d: Destinatario, actor: Usuario, request_id: str) -> Destinatario:
    """Borrado lógico (decisión #9): conserva datos e histórico sin anonimizar."""
    if not d.activo:
        raise ValueError("el destinatario ya está desactivado")
    d = await dest_repo.set_activo(db, d, False)
    await user_repo.save_audit(
        db, d.org_id, "recipient_deactivated", f"Destinatario desactivado: {d.correo} (datos conservados)",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("recipient_deactivated", request_id=request_id, destinatario_id=str(d.id_destinatarios))
    return d
