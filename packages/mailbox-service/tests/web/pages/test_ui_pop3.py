"""The mail pages of a POP3 account offer only what it can do: no flags,
folders, trash, filters or drafts, but deleting for good."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Candidate, Discovery, ProviderType

from ...ui_helpers import post, signed_in


@pytest.fixture
def pop3_browser(pop3_services: Services) -> TestClient:
    return signed_in(pop3_services)


def test_the_mail_page(pop3_browser: TestClient, pop3_account_id: str) -> None:
    page = pop3_browser.get(f"/ui/accounts/{pop3_account_id}/mail").text
    assert "Mail 3" in page
    assert "Delete for good" in page
    for absent in ("mark read", "move to …", "move to the trash", "New folder"):
        assert absent not in page
    assert 'href="/ui/accounts/' + pop3_account_id + '/drafts"' not in page
    assert 'name="text"' not in page  # the filter bar


def test_the_message_page(pop3_browser: TestClient, pop3_account_id: str) -> None:
    mail = pop3_browser.get(f"/ui/accounts/{pop3_account_id}/mail").text
    start = mail.index(f"/ui/accounts/{pop3_account_id}/mail/m")
    link = mail[start : mail.index('"', start)]
    page = pop3_browser.get(link).text
    assert "Delete for good" in page
    for absent in (
        "Mark read",
        "Mark unread",
        ">Star<",
        "Move to the trash",
        "Keywords",
    ):
        assert absent not in page


def test_the_account_page_names_pop3(
    pop3_browser: TestClient, pop3_account_id: str
) -> None:
    page = pop3_browser.get(f"/ui/accounts/{pop3_account_id}").text
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


def test_a_provider_with_pop3_alone(pop3_browser: TestClient) -> None:
    pop3_browser.app.state.services = replace(  # type: ignore[attr-defined]
        pop3_browser.app.state.services,  # type: ignore[attr-defined]
        discovery=OnlyPop3(),
    )
    page = post(pop3_browser, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert 'name="provider" value="pop3"' in page
    assert "POP3 server" in page and 'value="pop.example.org"' in page
    # Setting up by hand offers each kind, with what to know of it.
    assert "Set up IMAP by hand" in page and "Set up POP3 by hand" in page
    assert "the inbox only, no folders, no read state" in page
