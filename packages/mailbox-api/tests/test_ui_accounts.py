"""The account pages of the configuration UI."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import (
    Candidate,
    Discovery,
    Grant,
    Hint,
    ProviderType,
)
from benethos_mailbox_api.main import Services

from .conftest import bearer_for
from .ui_helpers import post, sign_in


class FoundBy:
    """Discovery without the network: always the same answer."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def discover(self, caller: Any, email: str) -> Discovery:
        caller.require("discover_account")
        self.asked.append(email)
        return Discovery(
            email=email,
            domain=email.rpartition("@")[2],
            candidates=[
                Candidate(
                    provider=ProviderType.IMAP,
                    name="Example Mail",
                    credential="app_password",
                    source="mx",
                    confirmed=False,
                    settings={"host": "imap.example.org", "port": 993},
                ),
                Candidate(
                    provider=ProviderType.GMAIL,
                    credential="oauth",
                    source="preset",
                    confirmed=True,
                ),
            ],
            hints=[Hint(text="Turn on IMAP in the provider's settings first.")],
        )


def test_the_list(ui: TestClient, account_id: str) -> None:
    page = ui.get("/ui/accounts").text
    assert "me@example.com" in page
    assert f'href="/ui/accounts/{account_id}"' in page
    assert "connected" in page
    assert "Connect an account" in page


def test_discovery_offers_what_can_be_connected(ui: TestClient) -> None:
    found = FoundBy()
    ui.app.state.discovery = found  # type: ignore[attr-defined]
    page = post(ui, "/ui/accounts/discover", {"email": "new@example.org"})
    assert found.asked == ["new@example.org"]
    assert page.status_code == 200
    assert "Example Mail" in page.text
    assert 'value="imap.example.org"' in page.text
    assert "check these servers" in page.text  # not from a trusted source
    assert "App password" in page.text
    assert "Turn on IMAP" in page.text
    assert "oauth" not in page.text.lower().split("what the sources answered")[0]


def test_connect_an_account(ui: TestClient, services: Services) -> None:
    created = post(
        ui,
        "/ui/accounts",
        {
            "email": "added@example.org",
            "display_name": "Added",
            "provider": "memory",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    location = created.headers["location"]
    assert location.startswith("/ui/accounts/acc_")
    page = ui.get(location).text
    assert "added@example.org connected." in page
    [account] = [
        services.adapters.record(i)
        for i in services.adapters.ids()
        if services.adapters.record(i).email == "added@example.org"
    ]
    assert account.display_name == "Added"


def test_an_unknown_provider_is_refused(ui: TestClient) -> None:
    answer = post(
        ui,
        "/ui/accounts",
        {"email": "x@example.org", "provider": "carrier-pigeon"},
        follow_redirects=False,
    )
    assert "err=Unknown+provider" in answer.headers["location"]


def test_change_verify_and_remove(ui: TestClient, account_id: str) -> None:
    url = f"/ui/accounts/{account_id}"
    page = ui.get(url).text
    assert account_id in page and "Remove account" in page
    saved = post(ui, url, {"display_name": "Renamed"})
    assert "Saved." in saved.text and "Renamed" in saved.text
    verified = post(ui, f"{url}/verify")
    assert "Status: connected." in verified.text
    removed = post(ui, f"{url}/delete")
    assert "Account removed" in removed.text
    assert "me@example.com" not in removed.text
    assert ui.get(url).status_code == 404


def test_a_reader_sees_no_forms(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services, Grant(accounts=[account_id], allow=["accounts.read", "mail.read"])
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    page = app_client.get(f"/ui/accounts/{account_id}").text
    assert "me@example.com" in page
    assert "Remove account" not in page and "New password" not in page
    assert "Connect an account" not in app_client.get("/ui/accounts").text
    assert app_client.get("/ui/accounts/new").status_code == 403
    refused = post(app_client, f"/ui/accounts/{account_id}/delete")
    assert "missing right" in refused.text


def test_an_unknown_account_is_404(ui: TestClient) -> None:
    assert ui.get("/ui/accounts/acc_nothing").status_code == 404


def test_a_failed_connect_never_echoes_the_password(ui: TestClient) -> None:
    """Here the keys do not exist yet, so storing fails."""
    answer = post(
        ui,
        "/ui/accounts",
        {"email": "x@example.org", "provider": "memory", "password": "s3cret-pw"},
        follow_redirects=False,
    )
    assert "err=" in answer.headers["location"]
    assert "s3cret-pw" not in answer.headers["location"]
    assert "s3cret-pw" not in ui.get(answer.headers["location"]).text


def test_only_changed_settings_are_sent() -> None:
    from benethos_mailbox_api.web.pages.routes.accounts import SETTING_FIELDS, _changed

    current = {"host": "imap.a.org", "port": 993, "username": "me"}
    every = set(SETTING_FIELDS)
    same = {"host": "imap.a.org", "port": 993, "username": "me"}
    assert _changed(current, same, every) == {}
    moved = {**same, "host": "imap.b.org"}
    assert _changed(current, moved, every) == {"host": "imap.b.org"}
    emptied = {"host": "imap.a.org", "username": "me"}
    assert _changed(current, emptied, every) == {"port": None}
    # A form that sends only the name removes nothing.
    assert _changed(current, {}, {"display_name", "csrf_token"}) == {}


def test_the_form_shows_the_settings(ui: TestClient, client: TestClient) -> None:
    created = client.post(
        "/v1/accounts",
        json={
            "provider": "memory",
            "email": "s@example.org",
            "settings": {"host": "imap.example.org", "smtp_host": "smtp.example.org"},
        },
    ).json()
    page = ui.get(f"/ui/accounts/{created['id']}").text
    assert 'name="host" value="imap.example.org"' in page
    assert 'name="smtp_host" value="smtp.example.org"' in page
