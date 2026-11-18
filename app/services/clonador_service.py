"""Importador de plantillas por URL (Opción A + B) — clona una página de login real.

Flujo de `importar_url`:
1. **Opción A (estática)**: `descargar_url` baja el HTML con httpx. Guardas SSRF estrictas
   (solo http/https, DNS resuelto y validado ANTES de conectar: sin loopback/privadas/
   link-local/metadata, máx 5 redirects validados por salto, máx 2 MB, timeout 10 s).
2. `necesita_render` detecta la carcasa vacía típica de un SPA (`<div id="root">` + scripts,
   casi sin texto). Si la hay, entra la **Opción B**: `renderizar_con_navegador` ejecuta la
   página en Chromium headless (Playwright) y captura el DOM final. Si Playwright no está
   instalado → 422 con mensaje claro.
3. `procesar_html` (PURO, testeado sin BD) "domestica" el HTML:
   - elimina <script>/<iframe>/<base>/meta CSP y refresh, atributos on* y javascript:;
   - absolutiza src/href/srcset contra la URL final;
   - TODO <form> queda action="/track/submit" method="post" (nunca postea al sitio real);
     el token por destinatario lo añadirá /track al servir la página (Fase 4);
   - si no hay <form> con <input type="password">, inyecta uno mínimo;
   - leyenda "PÁGINA DE PRUEBA" SOLO con leyenda=True (en imports está DESACTIVADA
     temporalmente para validar la previsualización del frontend).
4. `inlinar_css` baja cada <link rel=stylesheet> con las mismas guardas SSRF y lo inserta
   como <style data-fuente=...>: snapshot AUTOCONTENIDO → la previsualización (y /track)
   se ve idéntica aunque el entorno bloquee CSS externo (p. ej. el bundle de Meta ~1.1 MB).
   El resultado se guarda como `landing_html` de una plantilla normal: NO hay scraping en
   el momento del clic (snapshot congelado en la importación).
"""
import asyncio
import ipaddress
import re
import socket
import urllib.parse
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.logging import log_event
from app.services.plantilla_service import aplicar_leyenda

MAX_TAMANO = 2_000_000          # HTML de la página (Opción A): una landing no necesita más
MAX_REDIRECTS = 5
MAX_CSS_POR_HOJA = 1_500_000    # hoja CSS individual (el bundle de Meta pesa ~1.1 MB)
MAX_CSS_TOTAL = 2_000_000       # presupuesto acumulado de CSS inline
MAX_SNAPSHOT = 3_000_000        # landing final tras inlinear → 422 si se pasa
MAX_IMPORT_CSS = 2              # profundidad máxima de @import anidados
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
TIMEOUT_NAVEGADOR_MS = 20_000   # B: Chromium tarda más (SPA con red)
# UA de Chrome real: muchos sitios (Instagram, banks) sirven variantes pobres a UA desconocidos
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
ACCION_FORM = "/track/submit"   # marcador fijo; /track añade ?t={token} al servir (Fase 4)


# ---- Guardas SSRF (§ bloquear acceso a redes internas) ----

def _ip_bloqueada(ip: str) -> bool:
    """True si la IP NO puede visitarse: loopback, privadas, link-local, metadata de nubes."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        a.is_loopback or a.is_private or a.is_link_local or a.is_multicast
        or a.is_reserved or a.is_unspecified or not a.is_global
    )


async def _ips_de_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        datos = await loop.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f"no se pudo resolver el dominio '{host}'")
    return sorted({d[4][0] for d in datos})


async def _validar_url(url: str) -> urllib.parse.ParseResult:
    """Valida esquema/host y resuelve DNS; lanza ValueError si el destino está prohibido."""
    partes = urllib.parse.urlsplit(url)
    if partes.scheme not in ("http", "https"):
        raise ValueError("solo se permiten URLs http(s)")
    if not partes.hostname:
        raise ValueError("la URL no tiene dominio")
    for ip in await _ips_de_host(partes.hostname):
        if _ip_bloqueada(ip):
            raise ValueError(
                f"el dominio '{partes.hostname}' apunta a una dirección interna "
                f"({ip}) — no se permite por seguridad (SSRF)"
            )
    return partes


def _url_valida(url: str) -> urllib.parse.ParseResult:
    """Validación SÍNCRONA solo de formato (para rechazar antes de tocar red)."""
    partes = urllib.parse.urlsplit(url)
    if partes.scheme not in ("http", "https"):
        raise ValueError("solo se permiten URLs http(s)")
    if not partes.hostname:
        raise ValueError("la URL no tiene dominio")
    return partes


# ---- Opción A: descarga estática con guardas por salto ----

def _cliente() -> httpx.AsyncClient:
    """Separado para que los tests inyecten un MockTransport sin red real."""
    return httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT, headers=HEADERS)


async def descargar_url(url: str) -> tuple[str, str]:
    """Baja el HTML siguiendo redirects MANUALMENTE (validando cada destino). Retorna (html, url_final)."""
    url_actual = url
    async with _cliente() as c:
        for _ in range(MAX_REDIRECTS + 1):
            await _validar_url(url_actual)  # re-resuelve y re-valida en CADA salto
            try:
                resp = await c.get(url_actual)
            except httpx.HTTPError as e:
                raise ValueError(f"no se pudo descargar '{url_actual}': {str(e)[:120]}")
            location = resp.headers.get("location") if resp.is_redirect else None
            if location:
                url_actual = urllib.parse.urljoin(url_actual, location)
                continue
            break
        else:
            raise ValueError(f"demasiados redireccionamientos (máx {MAX_REDIRECTS})")

    await _validar_url(url_actual)  # mitigación extra de DNS rebinding (TOCTOU residual documentado)
    if resp.status_code >= 400:
        raise ValueError(f"el servidor respondió {resp.status_code} para '{url_actual}'")
    tipo = resp.headers.get("content-type", "")
    if "text/html" not in tipo:
        raise ValueError(f"la URL no es una página HTML (content-type: {tipo[:60]})")
    if len(resp.content) > MAX_TAMANO:
        raise ValueError(f"la página pesa más de {MAX_TAMANO // 1_000_000} MB")
    return resp.text, url_actual


# ---- Opción B: Chromium headless (Playwright) ----

def playwright_disponible() -> bool:
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


async def renderizar_con_navegador(url: str) -> str:
    """Opción B: ejecuta la página en Chromium headless y devuelve el DOM renderizado (str).

    Se usa SOLO cuando la descarga estática devolvió una carcasa SPA vacía. Sin guardas de
    red por conexión (el navegador hace su propio DNS) — la URL ya fue validada con las
    mismas reglas SSRF antes de lanzarlo.
    """
    if not playwright_disponible():
        raise ValueError(
            "esa página no expone contenido sin JavaScript y Playwright no está instalado "
            "en el servidor (contenedor api sin el paso 'playwright install chromium')"
        )
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        except Exception as e:  # noqa: BLE001 — instalación de Chromium rota/incompleta
            raise ValueError(f"no se pudo iniciar Chromium (Playwright): {str(e)[:120]}")
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=TIMEOUT_NAVEGADOR_MS)
            html = await page.content()
        except Exception as e:  # noqa: BLE001 — goto puede fallar por red/antibot/timeout
            raise ValueError(f"el navegador no pudo renderizar la página: {str(e)[:120]}")
        finally:
            await browser.close()
    return html


# ---- Detección de carcasa SPA (puro) ----

IDS_SPA = {"root", "app", "__next", "__nuxt", "application", "___gatsby", "q-app"}


def necesita_render(html: str) -> bool:
    """True si el HTML parece un shell de SPA sin contenido server-side (hay que renderizarlo).

    Heurística: casi nada de texto visible + marcador de framework (div#root/#__next/...)
    o cuerpo vacío con varios <script>.
    """
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)
    if len(texto) >= 300:
        return False
    body = soup.find("body")
    if body is not None:
        for el in body.find_all(id=True):
            if el.get("id") in IDS_SPA:
                return True
        for el in body.find_all("div", class_=True):
            clases = " ".join(el.get("class") or [])
            if "app" in clases.lower() and len(texto) < 100:
                return True
    return len(soup.find_all("script")) >= 2 and len(texto) < 100


# ---- Procesado puro del HTML (Opción A y B comparten esto) ----

ATRIBUTOS_SRC = ("src", "href", "action", "poster", "data-src")


def _absolutizar(soup: BeautifulSoup, base_url: str) -> None:
    """Convierte URLs relativas en absolutas contra la URL FINAL (tras redirects)."""
    for tag in soup.find_all(True):
        for attr in ATRIBUTOS_SRC:
            valor = tag.get(attr)
            if isinstance(valor, str) and valor.strip() and not valor.strip().lower().startswith(
                ("http://", "https://", "#", "mailto:", "tel:", "data:", "/track/")
            ):
                tag[attr] = urljoin(base_url, valor.strip())
        # srcset: cada candidato "url descriptor" se absolutiza por separado
        for attr in ("srcset", "data-srcset"):
            valor = tag.get(attr)
            if isinstance(valor, str) and valor.strip():
                candidatos = []
                for parte in valor.split(","):
                    parte = parte.strip()
                    if not parte:
                        continue
                    trozos = parte.split()
                    trozos[0] = urljoin(base_url, trozos[0])
                    candidatos.append(" ".join(trozos))
                if candidatos:
                    tag[attr] = ", ".join(candidatos)
        style = tag.get("style")
        if isinstance(style, str) and "url(" in style:
            tag["style"] = re.sub(r"url\((['\"]?)([^'\")]+)\1\)", lambda m: f"url({urljoin(base_url, m.group(2))})", style)

    for tag in soup.find_all("style"):
        if tag.string and "url(" in tag.string:
            tag.string = re.sub(r"url\((['\"]?)([^'\")]+)\1\)", lambda m: f"url({urljoin(base_url, m.group(2))})", tag.string)


def _domesticar(soup: BeautifulSoup) -> None:
    """Quita vida al snapshot: scripts, frames, base, CSP/refresh y atributos on*."""
    for sel in ("script", "iframe", "object", "embed", "base", "noscript"):
        for tag in soup.find_all(sel):
            tag.decompose()
    # meta CSP y refresh bloquearían el form propio o re-navegarían
    for tag in soup.find_all("meta"):
        equiv = (tag.get("http-equiv") or "").lower()
        if equiv in ("content-security-policy", "refresh"):
            tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag[attr]
            elif attr == "integrity" and tag.name == "link":
                del tag[attr]
        href = tag.get("href")
        if isinstance(href, str) and href.strip().lower().startswith("javascript:"):
            tag["href"] = "#"


def _forzar_forms(soup: BeautifulSoup) -> bool:
    """Todos los <form> → POST a /track/submit. Retorna True si ALGUNO captura contraseñas."""
    hay_password = False
    for form in soup.find_all("form"):
        form["action"] = ACCION_FORM
        form["method"] = "post"
        if form.find("input", attrs={"type": "password"}):
            hay_password = True
    return hay_password


FORM_MINIMO = (
    '<form action="{accion}" method="post">'
    '<p><input name="usuario" type="text" placeholder="Usuario" required></p>'
    '<p><input name="contrasena" type="password" placeholder="Contraseña" required></p>'
    '<p><button type="submit">Iniciar sesión</button></p>'
    '</form>'
)


# ---- Inlining de CSS: snapshot autocontenido (la previsualización se ve idéntica) ----

# @import url("x.css")  |  @import "x.css"  (con media query opcional antes del ;)
RE_IMPORT = re.compile(
    r"@import\s+(?:url\(\s*['\"]?([^'\")]+)['\"]?\s*\)|['\"]([^'\"]+)['\"])\s*[^;]*;", re.I
)
RE_URL_CSS = re.compile(r"url\((['\"]?)([^'\")]+)\1\)")


def _css_a_absoluto(css: str, css_url: str) -> str:
    """Absolutiza url() del CSS contra la URL de la HOJA (no de la página). PURO."""
    def _fix(m: re.Match) -> str:
        destino = m.group(2).strip()
        if destino.startswith(("data:", "#", "http://", "https:", "//")):
            return m.group(0)
        return f"url({m.group(1)}{urljoin(css_url, destino)}{m.group(1)})"
    return RE_URL_CSS.sub(_fix, css)


async def _traer_hoja(url: str, c: httpx.AsyncClient, profundidad: int = 0) -> Optional[str]:
    """Baja una hoja CSS con guardas SSRF, resuelve @import y absolutiza url(). None si no inlineable."""
    await _validar_url(url)
    try:
        resp = await c.get(url)
    except httpx.HTTPError:
        return None
    if resp.is_redirect:
        return None  # sin Location manejado aquí: los CDN de CSS rara vez redirigen
    tipo = resp.headers.get("content-type", "")
    if resp.status_code >= 400 or "text/css" not in tipo or len(resp.content) > MAX_CSS_POR_HOJA:
        return None
    css = resp.text
    if "</style" in css.lower():
        return None  # el contenido rompería el HTML al insertarlo en <style>
    # @import anidados: cada hoja importada se baja y absolutiza contra SU propia URL
    if profundidad < MAX_IMPORT_CSS and RE_IMPORT.search(css):
        partes: list[str] = []
        ultimo = 0
        for m in RE_IMPORT.finditer(css):
            partes.append(css[ultimo:m.start()])
            destino = (m.group(1) or m.group(2)).strip()
            sub = await _traer_hoja(urljoin(url, destino), c, profundidad + 1)
            partes.append(sub if sub is not None else m.group(0))
            ultimo = m.end()
        partes.append(css[ultimo:])
        css = "".join(partes)
    return _css_a_absoluto(css, url)


async def inlinar_css(html: str, base_url: str) -> str:
    """Inserta las hojas <link rel=stylesheet> como <style data-fuente=...> (snapshot autocontenido).

    Las previsualizaciones (iframe del frontend con CSP propia) y los clics reales ven
    EXACTAMENTE lo mismo sin depender de CDNs. Si una hoja no se puede bajar (403, no-CSS,
    demasiado grande) se conserva su <link>: degradación elegante, el import nunca falla
    por una hoja de estilos.
    """
    soup = BeautifulSoup(html, "html.parser")
    presupuesto = MAX_CSS_TOTAL
    async with _cliente() as c:
        for link in list(soup.find_all("link")):
            rel = link.get("rel") or []
            rel = " ".join(rel) if isinstance(rel, list) else str(rel)
            if "stylesheet" not in rel.lower():
                continue
            href = link.get("href")
            if not isinstance(href, str) or not href.strip() or presupuesto <= 0:
                continue
            css = await _traer_hoja(urljoin(base_url, href.strip()), c)
            if css is None:
                continue
            if len(css) > presupuesto:
                continue  # no cabe en el presupuesto restante → conserva su <link>
            presupuesto -= len(css)
            style = soup.new_tag("style")
            style["data-fuente"] = href.strip()
            style.string = css
            link.replace_with(style)
    return str(soup)


def procesar_html(html: str, base_url: str, leyenda: bool = False) -> str:
    """Convierte el HTML crudo (A o B) en una landing segura y funcional de Scytal. PURO.

    - absolutiza recursos contra `base_url` (la URL FINAL tras redirects),
    - domestica scripts/iframes/CSP/refresh/on*,
    - todos los forms → /track/submit; si ninguno pide contraseña, inyecta uno mínimo
      (los marcadores de posición nunca apuntan al sitio real),
    - la leyenda "PÁGINA DE PRUEBA" SOLO con leyenda=True: los imports la llevan
      DESACTIVADA temporalmente para validar la previsualización del frontend
      (las plantillas creadas a mano siguen recibiendo la leyenda en plantilla_service).
    """
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("body") is None:
        soup = BeautifulSoup(f"<html><body>{html}</body></html>", "html.parser")
    _domesticar(soup)
    _absolutizar(soup, base_url)
    if not _forzar_forms(soup):
        body = soup.find("body")
        envoltorio = BeautifulSoup(FORM_MINIMO.format(accion=ACCION_FORM), "html.parser")
        body.insert(0, envoltorio)

    if leyenda:
        return aplicar_leyenda(str(soup))
    return str(soup)


def _dominio(url: str) -> str:
    return _url_valida(url).hostname or "dominio"


CONTENIDO_IMPORTADO = (
    '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">'
    '<h2 style="color:#0d3b66;">Verificación de seguridad de tu cuenta</h2>'
    '<p>Hemos detectado actividad inusual asociada a tu cuenta. Para conservar el acceso, '
    'confirma tus credenciales en el siguiente enlace:</p>'
    '<p><a href="{{enlace}}">Verificar mi cuenta ahora</a></p>'
    '<p style="font-size:12px;color:#666;">Si no realizaste ninguna acción, ignora este mensaje.</p>'
    '{{pixel}}'
    '</div>'
)


# ---- Orquestación ----

async def importar_url(
    db, org_id, url: str,
    nombre: Optional[str], perfil: str, canal: str, asunto: Optional[str],
    actor, request_id: str,
):
    """Descarga (A), renderiza si hace falta (B), domestica, inlinea CSS y guarda."""
    from app.repositories import plantilla_repository as plantilla_repo
    from app.repositories import usuario_repository as user_repo

    partes = _url_valida(url)
    dominio = partes.hostname

    html, url_final = await descargar_url(url)
    if necesita_render(html):
        log_event("template_import_render", url=url_final)
        html = await renderizar_con_navegador(url_final)
    landing = procesar_html(html, url_final)   # sin leyenda por ahora (validación de frontend)
    landing = await inlinar_css(landing, url_final)
    if len(landing.encode("utf-8")) > MAX_SNAPSHOT:
        raise ValueError(f"la landing resultante pesa más de {MAX_SNAPSHOT // 1_000_000} MB")

    nombre_final = (nombre or f"Import {dominio}").strip()
    asunto_final = asunto or f"Verificación de seguridad de {dominio}"
    p = await plantilla_repo.create(
        db, org_id, nombre_final, perfil, canal, asunto_final, CONTENIDO_IMPORTADO, landing,
    )
    await user_repo.save_audit(
        db, org_id, "template_imported",
        f"Plantilla importada desde URL: {nombre_final} ({url_final})",
        actor_id=actor.id_usuarios,
    )
    await db.commit()
    log_event("template_imported", request_id=request_id, plantilla_id=str(p.id_plantillas), url=url_final)
    return p
