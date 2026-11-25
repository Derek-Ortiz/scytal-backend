import asyncio

import pytest

from app.core.config import get_settings
from app.services import email_service


class _FakeSes:
    def __init__(self):
        self.llamadas = []

    def send_email(self, **kwargs):
        self.llamadas.append(kwargs)
        return {"MessageId": "fake"}


@pytest.fixture(autouse=True)
def _limpiar_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ses_envia_mensaje_raw(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.setenv("EMAIL_FROM", "remitente@scytal.test")
    monkeypatch.setenv("SMTP_RETRY_ATTEMPTS", "1")
    fake = _FakeSes()
    monkeypatch.setattr(email_service, "_ses_client", lambda region: fake)

    ok = asyncio.run(email_service.send_email("dest@scytal.test", "Asunto", "texto", "<p>html</p>"))

    assert ok is True
    assert len(fake.llamadas) == 1
    params = fake.llamadas[0]
    assert params["FromEmailAddress"] == "remitente@scytal.test"
    assert params["Destination"] == {"ToAddresses": ["dest@scytal.test"]}
    assert b"Subject: Asunto" in params["Content"]["Raw"]["Data"]
    assert "ConfigurationSetName" not in params


def test_smtp_sigue_siendo_default(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    enviados = []

    async def _fake_smtp(msg):
        enviados.append(msg)

    monkeypatch.setattr(email_service, "_enviar_smtp", _fake_smtp)
    ok = asyncio.run(email_service.send_email("dest@scytal.test", "Hola", "texto"))
    assert ok is True and len(enviados) == 1


def test_proveedor_invalido_falla_sin_enviar(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier-pigeon")
    monkeypatch.setenv("SMTP_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("SMTP_RETRY_DELAY_SECONDS", "0")
    ok = asyncio.run(email_service.send_email("dest@scytal.test", "Hola", "texto"))
    assert ok is False
