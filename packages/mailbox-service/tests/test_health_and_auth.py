from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service import __version__
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.main import create_app


def test_health_needs_no_key(settings: Settings) -> None:
    response = TestClient(create_app(settings)).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_missing_key_is_rejected(settings: Settings) -> None:
    response = TestClient(create_app(settings)).get("/v1/accounts")
    assert response.status_code == 401


def test_wrong_key_is_rejected(settings: Settings) -> None:
    client = TestClient(create_app(settings), headers={"Authorization": "Bearer no"})
    assert client.get("/v1/accounts").status_code == 401


def test_unconfigured_key_serves_nothing() -> None:
    client = TestClient(create_app(Settings()), headers={"Authorization": "Bearer x"})
    assert client.get("/v1/accounts").status_code == 503


def test_auth_errors_use_the_error_envelope(settings: Settings) -> None:
    response = TestClient(create_app(settings)).get("/v1/accounts")
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_api_key_is_read_from_mailbox_service_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_KEY", "from-env")
    monkeypatch.setenv("MAILBOX_SERVICE_PORT", "9090")
    settings = Settings()
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "from-env"
    assert settings.port == 9090
