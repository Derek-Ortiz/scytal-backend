from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.middlewares.security_headers import SecurityHeadersMiddleware
from app.routers.auth import router as auth_router
from app.schemas.auth import error_payload

setup_logging()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Scytal — Backend de Autenticación", version="1.0.0")
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
        return JSONResponse(status_code=422, content=error_payload("VALIDATION_ERROR", "Datos inválidos", {"errors": exc.errors()}).model_dump())

    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "n/a")
        import logging
        logging.getLogger("scytal").error("unhandled", extra={"request_id": request_id})
        return JSONResponse(status_code=500, content=error_payload("INTERNAL_ERROR", "Error interno", {"request_id": request_id}).model_dump())

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "scytal-auth"}

    app.include_router(auth_router)
    return app


app = create_app()
