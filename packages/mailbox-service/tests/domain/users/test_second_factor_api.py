"""The second factor through the API: its state on a user, and removing
it (docs/AUTHENTICATION.md 6)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant, User
from benethos_mailbox_service.data.secrets import totp

from ...conftest import ADMIN, UI_PASSWORD, bearer_for

pytestmark = pytest.mark.usefixtures("master_key")

READER = Grant(accounts=["*"], allow=["mail.read"])


def with_factor(services: Services, name: str = "Anna") -> User:
    """A user who set up a second factor."""
    if not services.vault.initialized():
        services.vault.initialize()
    user = services.users.create_user(ADMIN, name, [], [READER], ui_sign_in=True)
    asyncio.run(
        services.auth.passwords.set(user.id, name, UI_PASSWORD, must_change=False)
    )
    access = services.auth.access_of(user.id)
    assert access is not None
    secret = asyncio.run(services.factors.begin(access, UI_PASSWORD))
    code = totp.code(secret, totp.step_of(datetime.now().astimezone()))
    services.factors.confirm(access, secret, code)
    return user


def test_a_user_says_whether_it_has_a_second_factor(
    client: TestClient, services: Services
) -> None:
    user = with_factor(services)
    assert client.get(f"/v1/users/{user.id}").json()["second_factor"] is True
    listed = client.get("/v1/users").json()["items"]
    assert {u["name"]: u["second_factor"] for u in listed}[user.name] is True
    others = [u for u in listed if u["name"] != user.name]
    assert others and not any(u["second_factor"] for u in others)


def test_removing_a_second_factor(client: TestClient, services: Services) -> None:
    user = with_factor(services)
    url = f"/v1/users/{user.id}/second-factor"
    assert client.delete(url).status_code == 204
    assert client.get(f"/v1/users/{user.id}").json()["second_factor"] is False
    assert not services.factors.has(user.id)
    gone = client.delete(url)
    assert gone.status_code == 404
    assert gone.json()["error"]["message"] == "Anna has no second factor"


def test_nobody_removes_its_own_through_the_api(
    client: TestClient, services: Services
) -> None:
    me = client.get("/v1/me").json()["user_id"]
    assert client.delete(f"/v1/users/{me}/second-factor").status_code == 409


def test_removing_needs_the_right(app_client: TestClient, services: Services) -> None:
    user = with_factor(services)
    reader = bearer_for(services, READER, service=["users.read"])
    refused = app_client.delete(f"/v1/users/{user.id}/second-factor", headers=reader)
    assert refused.status_code == 403
    assert services.factors.has(user.id)
