"""The account pages of the configuration UI."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from benethos_mailbox_service.data.models import (
    Candidate,
    Discovery,
    Grant,
    Hint,
    ProviderType,
)
from benethos_mailbox_service.main import Services

from ...conftest import browser_user
from ...ui_helpers import post, sign_in


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
    ui.app.state.services = replace(ui.app.state.services, discovery=found)  # type: ignore[attr-defined]
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
        ui, "/ui/accounts", {"email": "x@example.org", "provider": "carrier-pigeon"}
    )
    assert "Unknown provider." in answer.text


def test_change_verify_and_remove(ui: TestClient, account_id: str) -> None:
    url = f"/ui/accounts/{account_id}"
    page = ui.get(url).text
    assert account_id in page and "Remove account" in page
    assert '<a href="/ui/accounts">Accounts</a>' in page  # the breadcrumb
    # Facts first, then Change, then the danger card last.
    assert page.index("<h2>Account</h2>") < page.index("<h2>Change</h2>")
    assert page.index("<h2>Change</h2>") < page.index("Remove account")
    saved = post(ui, url, {"display_name": "Renamed"})
    assert "Saved." in saved.text and "Renamed" in saved.text
    verified = post(ui, f"{url}/verify")
    assert "Status: connected." in verified.text
    removed = post(ui, f"{url}/delete")
    assert "Account removed" in removed.text
    assert "me@example.com" not in removed.text
    assert ui.get(url).status_code == 404


def test_a_message_is_shown_once_and_never_taken_from_a_link(
    ui: TestClient, account_id: str
) -> None:
    url = f"/ui/accounts/{account_id}"
    saved = post(ui, url, {"display_name": "Renamed"})
    assert "Saved." in saved.text
    assert "Saved." not in str(saved.url)
    assert "Saved." not in ui.get(url).text
    forged = ui.get(f"{url}?err=Call+this+number&msg=Call+this+number").text
    assert "Call this number" not in forged


def test_a_reader_sees_no_forms(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services, Grant(accounts=[account_id], allow=["accounts.read", "mail.read"])
        ),
    )
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
        {
            "email": "x@example.org",
            "provider": "memory",
            "password": "s3cret-pw",
            "display_name": "Kept",
            "host": "imap.example.org",
        },
    )
    # The page again, the reason under the password, the fields kept.
    assert 'class="field-error"' in answer.text
    assert 'name="email" value="x@example.org"' in answer.text
    assert 'value="Kept"' in answer.text and 'value="imap.example.org"' in answer.text
    assert "s3cret-pw" not in str(answer.url)
    assert "s3cret-pw" not in answer.text


def test_the_settings_as_the_form_sent_them() -> None:
    from benethos_mailbox_service.web.pages.routes.accounts import _submitted

    form = FormData([("host", "imap.a.org"), ("port", ""), ("username", "me")])
    assert _submitted(form) == {"host": "imap.a.org", "port": None, "username": "me"}
    # A form that sends only the name removes nothing.
    assert _submitted(FormData([("display_name", "x")])) == {}


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


def test_accounts_filter_by_address_provider_and_status(
    ui: TestClient, services: Services, account_id: str
) -> None:
    from ...conftest import create_account

    create_account(services.accounts, "memory", "two@example.org")
    by_address = ui.get("/ui/accounts", params={"address": "TWO@"}).text
    assert "two@example.org" in by_address and "me@example.com" not in by_address
    by_status = ui.get("/ui/accounts", params={"status": "needs_reauth"}).text
    assert "No account matches." in by_status
    by_provider = ui.get("/ui/accounts", params={"provider": "memory"}).text
    assert "two@example.org" in by_provider and "Provider: memory" in by_provider
    assert "Filter:" in ui.get("/ui/accounts", params={"provider": "pigeon"}).text


def test_a_refused_change_keeps_what_was_typed(
    ui: TestClient, client: TestClient
) -> None:
    created = client.post(
        "/v1/accounts",
        json={
            "provider": "memory",
            "email": "c@example.org",
            "settings": {"host": "imap.example.org"},
        },
    ).json()
    url = f"/ui/accounts/{created['id']}"
    # Here the keys do not exist yet, so a new password cannot be stored.
    refused = post(
        ui,
        url,
        {
            "display_name": "Kept",
            "host": "imap2.example.org",
            "port": "10993",
            "password": "s3cret-pw",
        },
    )
    assert refused.status_code == 400
    assert 'class="notice err"' in refused.text
    assert 'name="display_name" value="Kept"' in refused.text
    assert 'name="host" value="imap2.example.org"' in refused.text
    assert 'value="10993"' in refused.text
    assert "s3cret-pw" not in refused.text
    assert 'name="host" value="imap.example.org"' in ui.get(url).text


def test_accounts_page_by_address(
    ui: TestClient, services: Services, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_service.web.pages.routes import accounts

    from ...conftest import create_account

    monkeypatch.setattr(accounts, "PAGE_SIZE", 2)
    for email in ("zed@example.org", "a@example.net"):
        create_account(services.accounts, "memory", email)
    first = ui.get("/ui/accounts").text
    assert "a@example.net" in first and "me@example.com" in first
    assert "zed@example.org" not in first
    on = re.search(r'href="([^"]*cursor=[^"]*)">Next', first)
    assert on is not None
    second = ui.get(html.unescape(on.group(1))).text
    assert "zed@example.org" in second and "a@example.net" not in second
    assert ">First</a>" in second
