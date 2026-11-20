import re

from app.services import password_service

async def test_contrasena_temporal_cumple_reglas(monkeypatch):
    from app.services.usuario_service import generate_temp_password

    for _ in range(20):
        pw = generate_temp_password()
        assert len(pw) >= 10
        assert password_service.validate_password and not await password_service.validate_password(pw)

async def test_contrasena_temporal_es_aleatoria(monkeypatch):
    from app.services.usuario_service import generate_temp_password

    pw1, pw2 = generate_temp_password(), generate_temp_password()
    assert pw1 != pw2
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", pw1)
