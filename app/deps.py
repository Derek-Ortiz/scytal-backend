import uuid

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.usuario import Usuario
from app.repositories import usuario_repository as user_repo


def _get_bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, detail={"error": {"code": "UNAUTHENTICATED", "message": "Token requerido"}})
    return auth[7:].strip()


def _claims_bearer(request: Request) -> dict:
    token = _get_bearer(request)
    try:
        claims = decode_token(token)
    except jwt.InvalidTokenError:
        raise HTTPException(401, detail={"error": {"code": "INVALID_TOKEN", "message": "Token inválido o expirado"}})
    if claims.get("tipo") != "access":
        raise HTTPException(401, detail={"error": {"code": "INVALID_TOKEN", "message": "Tipo de token incorrecto"}})
    return claims


async def _load_user(claims: dict, db: AsyncSession) -> Usuario:
    user = await user_repo.find_by_id(db, uuid.UUID(claims["sub"]))
    if user is None or not user.activo:
        raise HTTPException(401, detail={"error": {"code": "INVALID_TOKEN", "message": "Usuario no válido"}})
    if claims.get("version_token") != user.version_token:
        raise HTTPException(401, detail={"error": {"code": "SESSION_INVALIDATED", "message": "Sesión invalidada"}})
    return user


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> Usuario:
    """Para rutas de negocio: exige estado activo."""
    user = await _load_user(_claims_bearer(request), db)
    if user.estado != "activo":
        raise HTTPException(403, detail={"error": {"code": "PENDING_2FA", "message": "Debe completar el enrolamiento 2FA"}})
    return user


async def get_current_user_any_state(request: Request, db: AsyncSession = Depends(get_db)) -> Usuario:
    """Para /auth/me, /auth/logout y /auth/password/change: permite pendiente_2fa."""
    return await _load_user(_claims_bearer(request), db)


async def get_current_org(user: Usuario = Depends(get_current_user)):
    if user.org_id is None:
        raise HTTPException(403, detail={"error": {"code": "FORBIDDEN", "message": "Este usuario no pertenece a una organización"}})
    return user.org_id


async def get_pending_user(request: Request, db: AsyncSession = Depends(get_db)) -> Usuario:
    """Usuario con estado pendiente_2fa (enroll/confirm del TOTP)."""
    user = await _load_user(_claims_bearer(request), db)
    if user.estado != "pendiente_2fa":
        raise HTTPException(403, detail={"error": {"code": "ALREADY_ACTIVE", "message": "La cuenta ya está activa"}})
    return user
