import time
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


# ---- Contraseña Argon2id ----
def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, hash_: str) -> bool:
    try:
        return ph.verify(hash_, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hash_: str) -> bool:
    try:
        return ph.check_needs_rehash(hash_)
    except Exception:
        return False


# ---- JWT ----
def _payload(sub: str, token_type: str, extra: dict, expires: timedelta) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sub": sub,
        "tipo": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        **extra,
    }


def create_access_token(user_id: str, org_id: str | None, rol: str, version_token: int) -> str:
    s = get_settings()
    return jwt.encode(
        _payload(user_id, "access", {"org_id": org_id, "rol": rol, "version_token": version_token},
                 timedelta(minutes=s.JWT_ACCESS_EXPIRE_MINUTES)),
        s.JWT_SECRET, algorithm=s.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str, org_id: str | None, rol: str, version_token: int) -> str:
    s = get_settings()
    return jwt.encode(
        _payload(user_id, "refresh", {"org_id": org_id, "rol": rol, "version_token": version_token},
                 timedelta(days=s.JWT_REFRESH_EXPIRE_DAYS)),
        s.JWT_SECRET, algorithm=s.JWT_ALGORITHM,
    )


def create_pending_token(user_id: str, org_id: str | None, rol: str) -> str:
    s = get_settings()
    return jwt.encode(
        _payload(user_id, "pending", {"org_id": org_id, "rol": rol},
                 timedelta(minutes=s.JWT_PENDING_EXPIRE_MINUTES)),
        s.JWT_SECRET, algorithm=s.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALGORITHM])


# ---- TOTP + Fernet ----
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account: str, issuer: str = "Scytal") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(account, issuer_name=issuer)


def get_fernet() -> Fernet | None:
    key = get_settings().TOTP_ENCRYPTION_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def encrypt_totp_secret(secret: str) -> str:
    f = get_fernet()
    if f is None:
        raise ValueError("TOTP_ENCRYPTION_KEY no configurada")
    return f.encrypt(secret.encode()).decode()


def decrypt_totp_secret(encrypted: str) -> str:
    f = get_fernet()
    if f is None:
        raise ValueError("TOTP_ENCRYPTION_KEY no configurada")
    try:
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise ValueError("Secreto TOTP inválido")


def totp_step_now() -> int:
    return int(time.time() // 30)


def verify_totp(secret: str, code: str, last_step: int | None) -> tuple[bool, int | None]:
    """Verifica con valid_window=1 y control de replay por ultimo_totp_step."""
    if not code or not code.isdigit() or len(code) != 6:
        return False, None
    totp = pyotp.TOTP(secret)
    now_step = totp_step_now()
    for offset in (0, -1, 1):
        step = now_step + offset
        expected = totp.at(int(step * 30))
        if expected == code:
            if last_step is not None and step <= last_step:
                return False, None  # replay
            return True, step
    return False, None
