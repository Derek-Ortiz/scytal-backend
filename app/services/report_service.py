import csv
import io
import re
import unicodedata
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_ESTILOS = getSampleStyleSheet()
_TITULO = ParagraphStyle("TituloScytal", parent=_ESTILOS["Title"], fontSize=16, spaceAfter=6)
_SUBTITULO = ParagraphStyle("SubtituloScytal", parent=_ESTILOS["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
_CELDA = ParagraphStyle("CeldaScytal", parent=_ESTILOS["Normal"], fontSize=8)
_COLOR_CABECERA = colors.HexColor("#1f3b57")
_COLOR_FILA_PAR = colors.HexColor("#eef2f6")

EMBUDO_CLAVES = [
    ("Total destinatarios", "total"),
    ("Enviados", "enviados"),
    ("Abiertos", "abiertos"),
    ("Clics", "clics"),
    ("Envío de datos", "subidos"),
]

NIVELES = ("bajo", "medio", "alto", "critico")

def slug(texto: str, max_len: int = 40) -> str:
    base = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    return base[:max_len].strip("-") or "reporte"

def _celda(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, datetime):
        tz = v.strftime("%Z") or "UTC"
        return v.strftime(f"%Y-%m-%d %H:%M {tz}").strip()
    return str(v)

def _pct(n: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{100.0 * n / total:.1f}%"

def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def _tabla_html(filas: list[list[str]], anchos: list[int], cabecera: bool = True) -> Table:
    datos = [[Paragraph(str(c), _CELDA) for c in fila] for fila in filas]
    t = Table(datos, colWidths=[a * mm for a in anchos], repeatRows=1 if cabecera else 0)
    estilos = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b7c3cf")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if cabecera:
        estilos += [
            ("BACKGROUND", (0, 0), (-1, 0), _COLOR_CABECERA),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
        for i in range(1, len(filas)):
            if i % 2 == 0:
                estilos.append(("BACKGROUND", (0, i), (-1, i), _COLOR_FILA_PAR))
    t.setStyle(TableStyle(estilos))
    return t

def csv_campana(meta: list[tuple[str, object]], embudo: dict, tabla: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Reporte de campaña"])
    for etiqueta, valor in meta:
        w.writerow([etiqueta, _celda(valor)])
    w.writerow([])
    w.writerow(["Embudo"])
    w.writerow(["Métrica", "Valor", "% del total"])
    total = embudo["total"]
    for etiqueta, clave in EMBUDO_CLAVES:
        w.writerow([etiqueta, embudo[clave], _pct(embudo[clave], total)])
    w.writerow(["Clics QR (anónimos)", embudo["qr_clics"], "-"])
    w.writerow([])
    w.writerow(["Resultados por destinatario"])
    w.writerow(["correo", "enviado", "abrió", "clicó", "envío de datos", "puntaje", "nivel"])
    for f in tabla:
        w.writerow([
            f["correo"], _celda(f["enviado"]), _celda(f["abrio"]), _celda(f["clico"]),
            _celda(f["subio"]),
            "-" if f["puntaje_phishing"] is None else f["puntaje_phishing"],
            f["nivel"] or "-",
        ])
    return buf.getvalue().encode("utf-8-sig")

def csv_grupo(meta: list[tuple[str, object]], distribucion: dict, filas: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Reporte de madurez por grupo"])
    for etiqueta, valor in meta:
        w.writerow([etiqueta, _celda(valor)])
    w.writerow([])
    w.writerow(["Distribución por nivel (último puntaje)"])
    w.writerow(["nivel", "destinatarios"])
    for nivel in NIVELES:
        w.writerow([nivel, distribucion.get(nivel, 0)])
    w.writerow([])
    w.writerow(["Resultados por destinatario"])
    w.writerow(["correo", "activo", "último puntaje", "nivel"])
    for f in filas:
        w.writerow([
            f["correo"], _celda(f["activo"]),
            "-" if f["puntaje"] is None else f["puntaje"],
            f["nivel"] or "-",
        ])
    return buf.getvalue().encode("utf-8-sig")

def _pdf_base(titulo: str) -> tuple[io.BytesIO, SimpleDocTemplate, list]:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=titulo,
    )
    story: list = [Paragraph(titulo, _TITULO)]
    return buf, doc, story

def _meta_tabla(meta: list[tuple[str, object]]) -> Table:
    filas = [[etiqueta, _celda(valor)] for etiqueta, valor in meta]
    t = Table(filas, colWidths=[70 * mm, 160 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b7c3cf")),
        ("BACKGROUND", (0, 0), (0, -1), _COLOR_FILA_PAR),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t

def pdf_campana(meta: list[tuple[str, object]], embudo: dict, tabla: list[dict]) -> bytes:
    titulo = f"Reporte de campaña: {_celda(dict(meta).get('Campaña', 'sin nombre'))}"
    buf, doc, story = _pdf_base(titulo)
    story += [_meta_tabla(meta), Spacer(1, 6 * mm), Paragraph("Embudo de resultados", _SUBTITULO)]

    filas = [["Métrica", "Valor", "% del total"]]
    total = embudo["total"]
    for etiqueta, clave in EMBUDO_CLAVES:
        filas.append([etiqueta, str(embudo[clave]), _pct(embudo[clave], total)])
    filas.append(["Clics QR (anónimos)", str(embudo["qr_clics"]), "-"])
    story.append(_tabla_html(filas, [60, 30, 30]))

    story += [Spacer(1, 6 * mm), Paragraph("Resultados por destinatario", _SUBTITULO)]
    cabecera = ["Correo", "Enviado", "Abrió", "Clicó", "Envío de datos", "Puntaje", "Nivel"]
    filas = [cabecera]
    for f in tabla:
        filas.append([
            f["correo"], _celda(f["enviado"]), _celda(f["abrio"]), _celda(f["clico"]),
            _celda(f["subio"]),
            "-" if f["puntaje_phishing"] is None else str(f["puntaje_phishing"]),
            f["nivel"] or "-",
        ])
    story.append(_tabla_html(filas, [85, 22, 20, 20, 30, 25, 25]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Generado: {_ahora()}", _ESTILOS["Normal"]))
    doc.build(story)
    return buf.getvalue()

def pdf_grupo(meta: list[tuple[str, object]], distribucion: dict, filas: list[dict]) -> bytes:
    titulo = f"Reporte de madurez del grupo: {_celda(dict(meta).get('Grupo', 'sin nombre'))}"
    buf, doc, story = _pdf_base(titulo)
    story += [_meta_tabla(meta), Spacer(1, 6 * mm), Paragraph("Distribución por nivel (último puntaje)", _SUBTITULO)]

    dist = [["Nivel", "Destinatarios"]]
    for nivel in NIVELES:
        dist.append([nivel.capitalize(), str(distribucion.get(nivel, 0))])
    story.append(_tabla_html(dist, [40, 40]))

    story += [Spacer(1, 6 * mm), Paragraph("Resultados por destinatario", _SUBTITULO)]
    filas_pdf = [["Correo", "Activo", "Último puntaje", "Nivel"]]
    for f in filas:
        filas_pdf.append([
            f["correo"], _celda(f["activo"]),
            "-" if f["puntaje"] is None else str(f["puntaje"]),
            f["nivel"] or "-",
        ])
    story.append(_tabla_html(filas_pdf, [90, 25, 35, 30]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Generado: {_ahora()}", _ESTILOS["Normal"]))
    doc.build(story)
    return buf.getvalue()
