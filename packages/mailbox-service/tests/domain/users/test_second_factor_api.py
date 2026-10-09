"""The second factor through the API: its state on a user, its devices,
and removing one or all (docs/AUTHENTICATION.md 6)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant, User
from benethos_mailbox_service.data.secrets import totp

from ...conftest import ADMIN, UI_PASSWORD, bearer_for

pytestmark = pytest.mark.usefixtures("master_key")

READER = Grant(accounts=["*"], allow=["mail.read"])


def with_devices(services: Services, *names: str) -> User:
    """A user who added these devices to its second factor."""
    if not services.vault.initialized():
        services.vault.initialize()
    user = services.users.create_user(ADMIN, "Anna", [], [READER], ui_sign_in=True)
    asyncio.run(
        services.auth.passwords.set(user.id, "Anna", UI_PASSWORD, must_change=False)
    )
    access = services.auth.access_of(user.id)
    assert access is not None
    code = ""
    for name in names:
        kept, secret = asyncio.run(services.totp.begin(access, name, UI_PASSWORD, code))
        now = totp.code(secret, totp.step_of(datetime.now(UTC)))
        codes, _ = services.totp.confirm(access, kept, secret, now)
        code = codes[0] if codes else code
    return user


def test_a_user_says_whether_it_has_a_second_factor(
    client: TestClient, services: Services
) -> None:
    user = with_devices(services, "Phone")
    assert client.get(f"/v1/users/{user.id}").json()["second_factor"] is True
    listed = client.get("/v1/users").json()["items"]
    assert {u["name"]: u["second_factor"] for u in listed}[user.name] is True
    others = [u for u in listed if u["name"] != user.name]
    assert others and not any(u["second_factor"] for u in others)


def test_the_devices_of_a_user(client: TestClient, services: Services) -> None:
    user = with_devices(services, "Phone", "Tablet")
    answer = client.get(f"/v1/users/{user.id}/second-factor").json()
    assert [d["name"] for d in answer["totp"]] == ["Phone", "Tablet"]
    assert set(answer["totp"][0]) == {"id", "name", "created_at", "last_used_at"}
    # The first recovery code added the tablet.
    assert answer["recovery_codes_left"] == 9
    none = client.get(
        f"/v1/users/{client.get('/v1/me').json()['user_id']}/second-factor"
    )
    assert none.json() == {"totp": [], "recovery_codes_left": 0}


def test_removing_one_device(client: TestClient, services: Services) -> None:
    user = with_devices(services, "Phone", "Tablet")
    devices = client.get(f"/v1/users/{user.id}/second-factor").json()["totp"]
    url = f"/v1/users/{user.id}/second-factor/totp/{devices[0]['id']}"
    assert client.delete(url).status_code == 204
    left = client.get(f"/v1/users/{user.id}/second-factor").json()["totp"]
    assert [d["name"] for d in left] == ["Tablet"]
    assert client.delete(url).status_code == 404


def test_removing_every_device(client: TestClient, services: Services) -> None:
    user = with_devices(services, "Phone", "Tablet")
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
    own = f"/v1/users/{me}/second-factor/totp/tfa_x"
    assert client.delete(own).status_code == 409


def test_reading_and_removing_need_their_rights(
    app_client: TestClient, services: Services
) -> None:
    user = with_devices(services, "Phone")
    url = f"/v1/users/{user.id}/second-factor"
    reader = bearer_for(services, READER, service=["users.read"])
    assert app_client.get(url, headers=reader).status_code == 200
    assert app_client.delete(url, headers=reader).status_code == 403
    device = services.factors.of(ADMIN, user.id).totp[0].id
    refused = app_client.delete(f"{url}/totp/{device}", headers=reader)
    assert refused.status_code == 403
    nobody = bearer_for(services, READER)
    assert app_client.get(url, headers=nobody).status_code == 403
    assert services.factors.has(user.id)
