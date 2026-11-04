from zxcvbn import zxcvbn

from app.services import hibp_service


async def validate_password(password: str, recent_hashes: list[str] | None = None) -> list[str]:
    """Retorna lista de errores; vacío = válida (§5)."""
    from app.core.security import verify_password

    errors: list[str] = []
    if len(password) < 10:
        errors.append("La contraseña debe tener mínimo 10 caracteres")
    if hibp_service.is_locally_common(password):
        errors.append("La contraseña está en la lista de contraseñas comunes")
    result = zxcvbn(password)
    if result.get("score", 0) < 3:
        errors.append("La contraseña es demasiado débil (zxcvbn < 3)")
    if recent_hashes:
        for h in recent_hashes:
            if verify_password(password, h):
                errors.append("No puedes reutilizar una de tus últimas 3 contraseñas")
                break
    count = await hibp_service.hibp_count(password)
    if count > 0:
        errors.append("La contraseña aparece en filtraciones conocidas (HIBP)")
    return errors
