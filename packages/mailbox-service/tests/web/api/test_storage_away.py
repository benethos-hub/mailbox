"""While the database is away every route of the API answers 503 with
the code service_unavailable and Retry-After, the same with a token and
without, and the answer says nothing of a database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings

from ...conftest import admin_bearer
from .outage_helpers import CAUSE, RETRY, away


@pytest.mark.parametrize("token", [True, False], ids=["with a token", "without"])
def test_a_route_answers_503_while_the_database_is_away(
    settings: Settings,
    services: Services,
    monkeypatch: pytest.MonkeyPatch,
    token: bool,
) -> None:
    headers = admin_bearer(services) if token else {}
    away(services, monkeypatch, "tokens", "accounts")
    answer = TestClient(create_app(settings, services)).get(
        "/v1/accounts", headers=headers
    )
    assert answer.status_code == 503
    assert answer.headers["Retry-After"] == str(RETRY)
    error = answer.json()["error"]
    assert error == {
        "code": "service_unavailable",
        "message": "the service is not available at the moment",
    }
    assert "database" not in answer.text
    assert CAUSE not in answer.text
