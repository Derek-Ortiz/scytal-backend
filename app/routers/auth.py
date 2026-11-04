from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import check_limit
from app.db.session import get_db
from app.deps import get_current_user, get_current_user_any_state, get_pending_user
from app.models.usuario import Usuario
from app.schemas.auth import (
    ActionResponse, LoginRequest, LoginResponse, MeResponse, PasswordChangeRequest,
    RefreshRequest, RegisterRequest, RegisterResponse, TokenResponse, TotpConfirmRequest,
    TotpEnrollResponse, VerifyTotpRequest, error_payload,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _raise(code: str, message: str, status_code: int):
    raise HTTPException(status_code=status_code, detail=error_payload(code, message).model_dump())


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user, org = await auth_service.register(db, body.correo, body.contrasena, body.nombre_organizacion, body.slug, request.headers.get("x-request-id", ""))
    except ValueError as e:
        msg = str(e)
        if "ya existe" in msg or "ya está en uso" in msg:
            _raise("DUPLICATE", msg, 409)
        _raise("INVALID_PASSWORD", msg, 422)
    return RegisterResponse(id_usuarios=user.id_usuarios, correo=user.correo, rol=user.rol, estado=user.estado, org_id=org.id_organizaciones, nombre_organizacion=org.nombre, slug=org.slug)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    key = f"rl:login:{ip}:{body.correo.lower().strip()}"
    if not await check_limit(key, limit=10, window_seconds=900):
        _raise("RATE_LIMITED", "Demasiados intentos. Inténtalo de nuevo en 15 minutos.", 429)
    result = await auth_service.login(db, body.correo, body.contrasena, ip, request.headers.get("x-request-id", ""))
    if not result.get("ok"):
        _raise("INVALID_CREDENTIALS", "Correo o contraseña incorrectos", 401)
    # Sin TOTP configurado (cuenta nueva): token provisional para enroll/confirm.
    # Con TOTP configurado: pending_token de 5 min para verify-totp. Nunca JWT full hasta pasar TOTP.
    return LoginResponse(
        requires_totp=result["requires_totp"],
        must_enroll_totp=result["must_enroll_totp"],
        pending_token=result["pending_token"],
        provisional_access_token=result["provisional_access_token"],
        requires_password_change=result["requires_password_change"],
    )


@router.post("/login/verify-totp", response_model=TokenResponse)
async def verify_totp(body: VerifyTotpRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if not await check_limit(f"rl:totp:{body.pending_token[:32]}", limit=5, window_seconds=900):
        _raise("RATE_LIMITED", "Demasiados intentos de TOTP.", 429)
    try:
        tokens = await auth_service.verify_totp_login(db, body.pending_token, body.codigo, request.headers.get("x-request-id", ""))
    except ValueError as e:
        _raise("INVALID_TOTP", str(e), 401)
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        tokens = await auth_service.refresh(db, body.refresh_token)
    except ValueError as e:
        _raise("INVALID_TOKEN", str(e), 401)
    return TokenResponse(**tokens)


@router.post("/logout", response_model=ActionResponse)
async def logout(user: Usuario = Depends(get_current_user_any_state), db: AsyncSession = Depends(get_db)):
    await auth_service.logout(db, user)
    return ActionResponse()


@router.post("/totp/enroll", response_model=TotpEnrollResponse)
async def totp_enroll(user: Usuario = Depends(get_pending_user), db: AsyncSession = Depends(get_db)):
    data = auth_service.enroll_totp(user)
    await db.commit()
    return TotpEnrollResponse(**data)


@router.post("/totp/confirm", response_model=ActionResponse)
async def totp_confirm(body: TotpConfirmRequest, user: Usuario = Depends(get_pending_user), db: AsyncSession = Depends(get_db)):
    try:
        await auth_service.confirm_totp(db, user, body.codigo)
    except ValueError as e:
        _raise("INVALID_TOTP", str(e), 401)
    return ActionResponse(message="2FA activado")


@router.post("/password/change", response_model=ActionResponse)
async def password_change(body: PasswordChangeRequest, user: Usuario = Depends(get_current_user_any_state), db: AsyncSession = Depends(get_db)):
    try:
        await auth_service.change_password(db, user, body.contrasena_actual, body.contrasena_nueva)
    except ValueError as e:
        msg = str(e)
        if "incorrecta" in msg:
            _raise("INVALID_CREDENTIALS", msg, 401)
        _raise("INVALID_PASSWORD", msg, 422)
    return ActionResponse(message="Contraseña actualizada")


@router.get("/me", response_model=MeResponse)
async def me(user: Usuario = Depends(get_current_user_any_state)):
    return MeResponse(id_usuarios=user.id_usuarios, correo=user.correo, rol=user.rol, estado=user.estado, org_id=user.org_id, activo=user.activo, totp_habilitado=user.totp_habilitado, debe_cambiar_contrasena=user.debe_cambiar_contrasena)
