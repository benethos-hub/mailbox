from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service import __version__
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.main import Services, build_services, create_app

from .conftest import admin_bearer


@pytest.fixture
def api(settings: Settings, services: Services) -> TestClient:
    """The API with one user in it, and no token sent."""
    admin_bearer(services)
    return TestClient(create_app(settings, services))


def test_health_needs_no_token(settings: Settings) -> None:
    response = TestClient(create_app(settings)).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_a_missing_token_is_rejected(api: TestClient) -> None:
    assert api.get("/v1/accounts").status_code == 401


def test_a_wrong_token_is_rejected(api: TestClient) -> None:
    answer = api.get("/v1/accounts", headers={"Authorization": "Bearer no"})
    assert answer.status_code == 401


def test_without_any_user_nothing_is_served() -> None:
    client = TestClient(create_app(Settings()), headers={"Authorization": "Bearer x"})
    answer = client.get("/v1/accounts")
    assert answer.status_code == 503
    assert answer.json()["error"]["code"] == "setup_required"


def test_auth_errors_use_the_error_envelope(api: TestClient) -> None:
    response = api.get("/v1/accounts")
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_old_admin_key_is_not_read_but_named(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_KEY", "from-env")
    monkeypatch.setenv("MAILBOX_SERVICE_PORT", "9090")
    settings = Settings(storage="memory")
    assert settings.port == 9090
    with caplog.at_level(logging.WARNING):
        services = build_services(settings)
    assert "MAILBOX_SERVICE_KEY is set but no longer read" in caplog.text
    assert "from-env" not in caplog.text
    client = TestClient(
        create_app(settings, services), headers={"Authorization": "Bearer from-env"}
    )
    assert client.get("/v1/accounts").status_code == 503
