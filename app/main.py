from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.middlewares.security_headers import SecurityHeadersMiddleware
from app.routers.auth import router as auth_router
from app.routers.campaigns import router as campaigns_router
from app.routers.groups import router as groups_router
from app.routers.organizations import router as organizations_router
from app.routers.recipients import router as recipients_router
from app.routers.templates import router as templates_router
from app.routers.users import router as users_router
from app.schemas.auth import error_payload

setup_logging()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Scytal — Backend", version="1.2.0")
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in s.CORS_ALLOWED_ORIGINS.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # Errores estándar §6.5
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # exc.errors() puede incluir objetos ValueError en ctx (no serializables): se limpia
        errores = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
        return JSONResponse(status_code=422, content=error_payload("VALIDATION_ERROR", "Datos inválidos", {"errors": errores}).model_dump())

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        """Normaliza TODO HTTPException al formato §6.5 (sin el wrapper 'detail' de FastAPI)."""
        headers = getattr(exc, "headers", None)
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=headers)
        return JSONResponse(status_code=exc.status_code, content=error_payload("ERROR", str(exc.detail)).model_dump(), headers=headers)

    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "n/a")
        import logging
        logging.getLogger("scytal").error("unhandled", extra={"request_id": request_id})
        return JSONResponse(status_code=500, content=error_payload("INTERNAL_ERROR", "Error interno", {"request_id": request_id}).model_dump())

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "scytal"}

    app.include_router(auth_router)
    app.include_router(organizations_router)
    app.include_router(users_router)
    app.include_router(groups_router)
    app.include_router(recipients_router)
    app.include_router(templates_router)
    app.include_router(campaigns_router)
    return app


app = create_app()
