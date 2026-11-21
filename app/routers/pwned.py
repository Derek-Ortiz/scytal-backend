from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.rate_limit import check_limit
from app.core.security import decode_token
from app.schemas.auth import error_payload
from app.schemas.pwned import PwnedRangeResponse, StrengthCheckRequest, StrengthCheckResponse
from app.services import hibp_service, password_service

router = APIRouter(prefix="/pwned", tags=["pwned"])

VENTANA_SEG = 60
LIMITE_IP = 10
LIMITE_SESION = 20
RETRY_AFTER = {"Retry-After": str(VENTANA_SEG)}

def _sub_token(request: Request) -> str | None:
    """sub del bearer si es un access token válido; None si no hay o no sirve (endpoint es público)."""
    import jwt as pyjwt

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        claims = decode_token(auth[7:].strip())
    except pyjwt.InvalidTokenError:
        return None
    if claims.get("tipo") != "access":
        return None
    return claims.get("sub")

async def _limitar(request: Request, recurso: str) -> None:
    """§6.2: público 10/min por IP, autenticado 20/min por sesión. Falla abierto sin Redis."""
    sub = _sub_token(request)
    if sub is not None:
        clave, limite = f"rl:pwned:{recurso}:u:{sub}", LIMITE_SESION
    else:
        ip = request.client.host if request.client else "anonima"
        clave, limite = f"rl:pwned:{recurso}:ip:{ip}", LIMITE_IP
    if not await check_limit(clave, limit=limite, window_seconds=VENTANA_SEG):
        raise HTTPException(
            status_code=429,
            detail=error_payload("RATE_LIMITED", "Demasiadas solicitudes; espera un minuto.").model_dump(),
            headers=RETRY_AFTER,
        )

@router.get("/range/{prefijo}", response_model=PwnedRangeResponse)
async def pwned_range(
    prefijo: str,
    request: Request,
):
    """Proxy cacheado hacia HIBP con k-anonimato (§4.2): solo viajan los 5 primeros hex del SHA-1."""
    await _limitar(request, "range")
    if len(prefijo) != 5 or any(c not in "0123456789abcdefABCDEF" for c in prefijo):
        raise HTTPException(
            status_code=422,
            detail=error_payload("VALIDATION_ERROR", "El prefijo debe ser exactamente 5 caracteres hexadecimales").model_dump(),
        )
    conteos = await hibp_service.rango(prefijo)
    if conteos is None:
        raise HTTPException(
            status_code=503,
            detail=error_payload("HIBP_UNAVAILABLE", "El servicio de contraseñas filtradas no está disponible; intenta más tarde").model_dump(),
        )
    resp = PwnedRangeResponse(prefijo=prefijo.upper(), total_conocidas=len(conteos), conteos=conteos)
    return JSONResponse(
        content=resp.model_dump(mode="json"),
        headers={"Cache-Control": f"private, max-age={get_settings().HIBP_CACHE_TTL_SECONDS}"},
    )

@router.post("/strength-check", response_model=StrengthCheckResponse)
async def strength_check(
    body: StrengthCheckRequest,
    request: Request,
):
    """Chequeo rápido de fortaleza con zxcvbn + lista local, SIN llamar a HIBP (§4.2)."""
    await _limitar(request, "strength")
    return StrengthCheckResponse(**password_service.fortaleza_local(body.password))
