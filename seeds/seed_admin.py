"""Crea el único admin_plataforma si no existe. Lee de .env. Uso: `python -m seeds.seed_admin`."""
import asyncio
import sys

sys.path.insert(0, "/srv/app")

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.historial import HistorialContrasenas
from app.models.usuario import Usuario
from app.services.password_service import validate_password


async def main():
    s = get_settings()
    email = s.PLATFORM_ADMIN_EMAIL.lower().strip()
    from app.repositories.usuario_repository import find_by_email
    async with SessionLocal() as db:
        if await find_by_email(db, email):
            print(f"admin_plataforma {email} ya existe, nada que hacer.")
            return
        errors = await validate_password(s.PLATFORM_ADMIN_PASSWORD)
        if errors:
            print(f"La contraseña de PLATFORM_ADMIN_PASSWORD no cumple §5: {'; '.join(errors)}")
            return
        h = hash_password(s.PLATFORM_ADMIN_PASSWORD)
        user = Usuario(org_id=None, correo=email, rol="admin_plataforma", hash_contrasena=h, estado="pendiente_2fa", activo=True)
        db.add(user)
        await db.flush()
        db.add(HistorialContrasenas(usuario_id=user.id_usuarios, hash_contrasena=h))
        await db.commit()
        print(f"admin_plataforma creado: {email} (estado pendiente_2fa, debe enrolar TOTP)")


if __name__ == "__main__":
    asyncio.run(main())
