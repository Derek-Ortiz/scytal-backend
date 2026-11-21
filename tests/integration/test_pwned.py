import pytest

pytestmark = pytest.mark.integration

from tests.conftest import integration_guard
from tests.integration.test_groups import _org_con_token

@pytest.fixture(autouse=True)
async def _limpiar_rate_limit():
    from app.core.rate_limit import _get_redis

    async def _limpiar():
        r = _get_redis()
        if r is None:
            return
        try:
            claves = await r.keys("rl:pwned:*")
            if claves:
                await r.delete(*claves)
        except Exception:
            pass

    await _limpiar()
    yield
    await _limpiar()

CONTRASENA_DEBIL = "password123"
CONTRASENA_FUERTE = "Correcta-Caballo-42-Bateria!"

@pytest.mark.asyncio
async def test_pwned_range_valido_y_invalido(client, integration_guard, monkeypatch):
    from app.services import hibp_service

    async def _falso_rango(prefijo: str) -> dict[str, int]:
        return {"AAAAAA": 3, "BBBBBB": 1000}

    monkeypatch.setattr(hibp_service, "rango", _falso_rango)

    r = await client.get("/pwned/range/abcde")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["prefijo"] == "ABCDE" and data["total_conocidas"] == 2
    assert data["conteos"] == {"AAAAAA": 3, "BBBBBB": 1000}
    assert "max-age=" in r.headers.get("cache-control", "")

    r = await client.get("/pwned/range/ABCDE")
    assert r.status_code == 200

    for malo in ("abc", "abcdef", "zzzzz", "ab1xy"):
        r = await client.get(f"/pwned/range/{malo}")
        assert r.status_code == 422, f"{malo} → {r.status_code}"
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

@pytest.mark.asyncio
async def test_pwned_range_hibp_caido(client, integration_guard, monkeypatch):
    from app.services import hibp_service

    async def _fallo(prefijo: str) -> dict[str, int] | None:
        return None

    monkeypatch.setattr(hibp_service, "rango", _fallo)
    r = await client.get("/pwned/range/abcde")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "HIBP_UNAVAILABLE"

@pytest.mark.asyncio
async def test_pwned_strength_check(client, integration_guard):
    r = await client.post("/pwned/strength-check", json={"password": CONTRASENA_DEBIL})
    assert r.status_code == 200, r.text
    debil = r.json()
    assert debil["es_fuerte"] is False and debil["score"] < 3 and len(debil["errores"]) >= 1

    r = await client.post("/pwned/strength-check", json={"password": CONTRASENA_FUERTE})
    assert r.status_code == 200
    fuerte = r.json()
    assert fuerte["es_fuerte"] is True and fuerte["score"] >= 3 and fuerte["errores"] == []

    r = await client.post("/pwned/strength-check", json={"password": "corta"})
    assert r.status_code == 200 and r.json()["es_fuerte"] is False

    r = await client.post("/pwned/strength-check", json={})
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_pwned_rate_limit_por_ip(client, integration_guard, monkeypatch):
    from app.services import hibp_service

    async def _falso_rango(prefijo: str) -> dict[str, int]:
        return {"AAAAAA": 1}

    monkeypatch.setattr(hibp_service, "rango", _falso_rango)

    estados = []
    for _ in range(11):
        r = await client.get("/pwned/range/abcde")
        estados.append(r.status_code)
    assert estados[:10] == [200] * 10, estados
    assert estados[10] == 429
    assert r.headers.get("retry-after") == "60"
    assert r.json()["error"]["code"] == "RATE_LIMITED"

    r = await client.post("/pwned/strength-check", json={"password": CONTRASENA_FUERTE})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_pwned_rate_limit_por_sesion(client, integration_guard, monkeypatch):
    from app.services import hibp_service

    async def _falso_rango(prefijo: str) -> dict[str, int]:
        return {"AAAAAA": 1}

    monkeypatch.setattr(hibp_service, "rango", _falso_rango)
    reg, tok = await _org_con_token(client, "pwned")
    headers = {"Authorization": f"Bearer {tok}"}

    estados = []
    for _ in range(21):
        r = await client.get("/pwned/range/abcde", headers=headers)
        estados.append(r.status_code)
    assert estados[:20] == [200] * 20, estados
    assert estados[20] == 429
