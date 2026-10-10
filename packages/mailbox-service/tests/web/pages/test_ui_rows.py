"""Lists that act in the row (docs/UI.md 4.2): the plus in a card's
header opens the form at the head of the list, a pencil the form under
its row, a bin the question, and ticked rows go together."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant, User
from benethos_mailbox_service.data.secrets import totp

from ...conftest import ADMIN, UI_PASSWORD, browser_user
from ...ui_helpers import post, sign_in, try_sign_in

READER = Grant(accounts=["*"], allow=["mail.read"])


def _code(secret: bytes, steps: int) -> str:
    return totp.code(secret, totp.step_of(datetime.now(UTC)) + steps)


def _two_devices(services: Services, name: str) -> list[str]:
    """Phone and Tablet for the user of this name: the recovery codes."""
    user = services.auth.user_named(name)
    assert user is not None
    access = services.auth.access_of(user.id)
    assert access is not None
    begun = asyncio.run(services.totp.begin(access, "Phone", UI_PASSWORD))
    kept, phone = begun.name, begun.secret
    codes = services.totp.confirm(access, kept, phone, _code(phone, 0)).recovery_codes
    begun = asyncio.run(services.totp.begin(access, "Tablet", UI_PASSWORD, codes[0]))
    services.totp.confirm(access, begun.name, begun.secret, _code(begun.secret, 0))
    return codes


def _sign_in_with_code(client: TestClient, name: str, password: str, code: str) -> None:
    try_sign_in(client, name, password)
    page = client.get("/ui/login/code")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    client.post("/ui/login/code", data={"code": code, "nonce": nonce.group(1)})


def _devices(services: Services, user: User) -> dict[str, str]:
    return {d.name: d.id for d in services.factors.of(ADMIN, user.id).totp}


# --- devices --------------------------------------------------------------------------


@pytest.mark.usefixtures("master_key")
def test_each_device_has_its_pencil_and_bin_and_a_dialog(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, password = browser_user(services, READER)
    codes = _two_devices(services, name)
    _sign_in_with_code(app_client, name, password, codes[1])
    page = app_client.get("/ui/second-factor").text
    user = services.auth.user_named(name)
    assert user is not None
    phone = _devices(services, user)["Phone"]
    # The plus in the header opens the form at the head of the list.
    assert 'data-toggle="add-device" aria-controls="add-device"' in page
    assert '<tr class="row-form" id="add-device">' in page
    # The pencil folds out the form under its row, the bin opens a dialog
    # that asks for the password and a code.
    assert 'aria-label="Rename Phone"' in page
    assert f'<tr class="row-form" id="rename-{phone}">' in page
    assert f'data-dialog="remove-{phone}"' in page
    assert f'<dialog class="ask form-dialog" id="remove-{phone}"' in page
    # Two devices: a tick box each and the bar above them.
    assert page.count('form="devices-batch"') == 2
    assert 'data-dialog="remove-ticked"' in page


@pytest.mark.usefixtures("master_key")
def test_ticked_devices_go_after_one_password_and_one_code(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, password = browser_user(services, READER)
    codes = _two_devices(services, name)
    _sign_in_with_code(app_client, name, password, codes[1])
    user = services.auth.user_named(name)
    assert user is not None
    ticked = list(_devices(services, user).values())
    refused = post(
        app_client,
        "/ui/second-factor/totp/remove-ticked",
        {"device": ticked, "password": password, "code": "000000"},
    )
    assert "the code is not right" in refused.text
    assert len(_devices(services, user)) == 2
    removed = post(
        app_client,
        "/ui/second-factor/totp/remove-ticked",
        {"device": ticked, "password": password, "code": codes[2]},
    )
    assert "Devices removed. The second factor is off." in removed.text
    assert not services.factors.has(user.id)


@pytest.mark.usefixtures("master_key")
def test_another_users_device_goes_from_its_row(
    ui: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, _ = browser_user(services, READER)
    _two_devices(services, name)
    user = services.auth.user_named(name)
    assert user is not None
    page = ui.get(f"/ui/users/{user.id}?tab=access").text
    assert 'aria-label="Remove Phone"' in page and "Remove every device" in page
    phone = _devices(services, user)["Phone"]
    post(ui, f"/ui/users/{user.id}/second-factor/totp/{phone}/remove")
    assert list(_devices(services, user)) == ["Tablet"]


# --- tokens ---------------------------------------------------------------------------


def test_tokens_are_made_at_the_head_and_revoked_in_their_row(
    ui: TestClient, services: Services
) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    url = f"/ui/users/{user.id}?tab=access"
    empty = ui.get(url).text
    # No token yet: the form at the head of the list is open at once.
    assert '<tr class="row-form open" id="new-token">' in empty
    services.auth.issue_token(user.id, "one")
    page = ui.get(url).text
    assert '<tr class="row-form" id="new-token">' in page
    assert 'aria-label="Revoke one"' in page
    # One active token: nothing to tick.
    assert 'id="tokens-batch"' not in page


def test_ticked_tokens_are_revoked_together(ui: TestClient, services: Services) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    one = services.auth.issue_token(user.id, "one").token
    two = services.auth.issue_token(user.id, "two").token
    url = f"/ui/users/{user.id}"
    page = ui.get(f"{url}?tab=access").text
    assert 'id="tokens-batch"' in page and page.count('form="tokens-batch"') == 2
    assert 'data-confirm="Revoke the ticked tokens?' in page
    nothing = post(ui, f"{url}/tokens/revoke")
    assert "tick at least one token" in nothing.text
    revoked = post(ui, f"{url}/tokens/revoke", {"token": [one.id, two.id]})
    assert "2 tokens revoked." in revoked.text
    assert all(t.revoked_at for t in services.tokens.list_tokens(ADMIN, user.id))


def test_a_reader_sees_no_plus_and_no_tick(
    app_client: TestClient, services: Services
) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    services.auth.issue_token(user.id, "one")
    services.auth.issue_token(user.id, "two")
    sign_in(app_client, *browser_user(services, service=["users.read"]))
    page = app_client.get(f"/ui/users/{user.id}?tab=access").text
    assert "<h2>Tokens</h2>" in page
    assert 'id="new-token"' not in page and 'id="tokens-batch"' not in page
    assert 'aria-label="Revoke one"' not in page
