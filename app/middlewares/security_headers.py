import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

CSP_API = "default-src 'none'; frame-ancestors 'none'"
# CSP relajada solo para la UI interactiva (/docs, /redoc): Swagger UI carga CSS/JS
# del CDN y usa un script inline; el resto de rutas usa la CSP estricta.
RUTAS_DOCS = ("/docs", "/redoc", "/openapi.json")
CSP_DOCS = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src https://cdn.jsdelivr.net data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        csp = CSP_DOCS if request.url.path.startswith(RUTAS_DOCS) else CSP_API
        response.headers["Content-Security-Policy"] = csp
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time"] = f"{(time.time() - start) * 1000:.1f}ms"
        return response
