"""The mail pages of a POP3 account offer only what it can do: no flags,
folders, trash, filters or drafts, but deleting for good."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Candidate, Discovery, ProviderType

from ...conftest import browser_admin
from ...domain.sync.test_pop3_sync import pop3_account_id, pop3_server, pop3_services
from ...ui_helpers import post, sign_in

__all__ = ["pop3_account_id", "pop3_server", "pop3_services"]  # fixtures


@pytest.fixture
def browser(pop3_services: Services) -> TestClient:
    client = TestClient(create_app(Settings(storage="memory"), pop3_services))
    sign_in(client, *browser_admin(pop3_services))
    return client


def test_the_mail_page(browser: TestClient, pop3_account_id: str) -> None:
    page = browser.get(f"/ui/accounts/{pop3_account_id}/mail").text
    assert "Mail 3" in page
    assert "Delete for good" in page
    for absent in ("mark read", "move to …", "move to the trash", "New folder"):
        assert absent not in page
    assert 'href="/ui/accounts/' + pop3_account_id + '/drafts"' not in page
    assert 'name="text"' not in page  # the filter bar


def test_the_message_page(browser: TestClient, pop3_account_id: str) -> None:
    mail = browser.get(f"/ui/accounts/{pop3_account_id}/mail").text
    start = mail.index(f"/ui/accounts/{pop3_account_id}/mail/m")
    link = mail[start : mail.index('"', start)]
    page = browser.get(link).text
    assert "Delete for good" in page
    for absent in (
        "Mark read",
        "Mark unread",
        ">Star<",
        "Move to the trash",
        "Keywords",
    ):
        assert absent not in page


def test_the_account_page_names_pop3(browser: TestClient, pop3_account_id: str) -> None:
    page = browser.get(f"/ui/accounts/{pop3_account_id}").text
    assert "POP3" in page and "POP3 server" in page
    assert "995 for tls, 110 for starttls" in page


class OnlyPop3:
    """Discovery without the network: a provider with POP3 alone."""

    async def discover(self, caller: Any, email: str) -> Discovery:
        return Discovery(
            email=email,
            domain="example.org",
            candidates=[
                Candidate(
                    provider=ProviderType.POP3,
                    name="Old Mail",
                    credential="password",
                    source="ispdb",
                    confirmed=True,
                    settings={"host": "pop.example.org", "port": 995},
                )
            ],
        )


def test_a_provider_with_pop3_alone(browser: TestClient) -> None:
    browser.app.state.services = replace(  # type: ignore[attr-defined]
        browser.app.state.services,  # type: ignore[attr-defined]
        discovery=OnlyPop3(),
    )
    page = post(browser, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert 'name="provider" value="pop3"' in page
    assert "POP3 server" in page and 'value="pop.example.org"' in page
    # Setting up by hand offers both.
    assert '<option value="pop3">' in page and '<option value="imap" selected>' in page
