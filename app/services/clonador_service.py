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
   - absolutiza src/hrelativos contra la URL final;
   - TODO <form> queda action="/track/submit" method="post" (nunca postea al sitio real);
     el token por destinatario lo añadirá /track al servir la página (Fase 4);
   - si no hay <form> con <input type="password">, inyecta uno mínimo;
   - garantiza la leyenda "PÁGINA DE PRUEBA" (reusa plantilla_service).
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

MAX_TAMANO = 2_000_000          # 2 MB: una landing no necesita más (anti-DoS)
MAX_REDIRECTS = 5
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
TIMEOUT_NAVEGADOR_MS = 20_000   # B: Chromium tarda más (SPA con red)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ScytalTemplateImport/1.0)"}
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


def procesar_html(html: str, base_url: str) -> str:
    """Convierte el HTML crudo (A o B) en una landing segura y funcional de Scytal. PURO.

    - absolutiza recursos contra `base_url` (la URL FINAL tras redirects),
    - domestica scripts/iframes/CSP/refresh/on*,
    - todos los forms → /track/submit; si ninguno pide contraseña, inyecta uno mínimo
      (los marcadores de posición nunca apuntan al sitio real),
    - garantiza la leyenda "PÁGINA DE PRUEBA".
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

    # leyenda obligatoria (reusa plantilla_service)
    return aplicar_leyenda(str(soup))


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
    """Descarga (A), renderiza si hace falta (B), procesa y guarda la plantilla."""
    from app.repositories import plantilla_repository as plantilla_repo
    from app.repositories import usuario_repository as user_repo

    partes = _url_valida(url)
    dominio = partes.hostname

    html, url_final = await descargar_url(url)
    if necesita_render(html):
        log_event("template_import_render", url=url_final)
        html = await renderizar_con_navegador(url_final)
    landing = procesar_html(html, url_final)

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
