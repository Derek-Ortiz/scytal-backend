from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://scytal:scytal_pass@db:5432/scytal"
    REDIS_URL: str = "redis://redis:6379/0"

    JWT_SECRET: str = "cambia-este-secreto"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    JWT_PENDING_EXPIRE_MINUTES: int = 5

    TOTP_ENCRYPTION_KEY: str = ""

    SMTP_HOST: str = "mailhog"
    SMTP_PORT: int = 1025
    SMTP_FROM: str = "no-reply@scytal.local"

    PUBLIC_BASE_URL: str = "http://localhost:8000"

    HIBP_API_URL: str = "https://api.pwnedpasswords.com/range/"
    HIBP_CACHE_TTL_SECONDS: int = 3600

    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"

    PLATFORM_ADMIN_EMAIL: str = "admin@scytal.local"
    PLATFORM_ADMIN_PASSWORD: str = "CambiaEstaClave123!"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
