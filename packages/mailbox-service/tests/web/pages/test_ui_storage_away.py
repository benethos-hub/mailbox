"""The UI while the database fails: the page says so, and nobody who is
signed in is signed out by it."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.errors import StorageUnavailableError

from ...conftest import browser_admin
from ..outage_helpers import CAUSE, RETRY, away


def test_a_failing_database_signs_nobody_out(
    ui: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = services.auth.session_access
    calls: list[int] = []

    def once(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise StorageUnavailableError(RETRY, CAUSE)
        return real(*args, **kwargs)

    monkeypatch.setattr(services.auth, "session_access", once)
    answer = ui.get("/ui", follow_redirects=False)
    assert answer.status_code == 503
    assert answer.headers["Retry-After"] == str(RETRY)
    assert CAUSE not in answer.text
    again = ui.get("/ui", follow_redirects=False)
    assert again.status_code == 200


def test_a_sign_in_while_the_database_is_away(
    app_client: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, password = browser_admin(services)
    page = app_client.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    away(services, monkeypatch, "passwords")
    answer = app_client.post(
        "/ui/login",
        data={"name": name, "password": password, "nonce": nonce.group(1)},
        follow_redirects=False,
    )
    assert answer.status_code == 503
    assert answer.headers["Retry-After"] == str(RETRY)
