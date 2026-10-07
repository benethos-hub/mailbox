"""A JMAP account in the configuration UI: connected by hand or from what
discovery found, with a password or an API token, and its page."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Candidate, Discovery, ProviderType

from ...conftest import browser_admin
from ...domain.sync.test_jmap_sync import account_id, jmap_services, server
from ...jmap_fake import HOST, TOKEN, FakeJmap
from ...ui_helpers import post, sign_in

__all__ = ["account_id", "jmap_services", "server"]  # fixtures


@pytest.fixture
def browser(jmap_services: Services) -> TestClient:
    client = TestClient(create_app(Settings(storage="memory"), jmap_services))
    sign_in(client, *browser_admin(jmap_services))
    return client


def test_the_account_page(browser: TestClient, account_id: str) -> None:
    page = browser.get(f"/ui/accounts/{account_id}").text
    assert "JMAP server" in page and "Session path" in page
    assert "SMTP server" not in page and "New password" in page
    # Everything a mail client does is offered.
    mail = browser.get(f"/ui/accounts/{account_id}/mail").text
    assert "move to the trash" in mail and "New folder" in mail


class NothingFound:
    """Discovery without the network, which finds nothing."""

    async def discover(self, caller: Any, email: str) -> Discovery:
        return Discovery(email=email, domain="example.org")


def test_connect_by_hand_with_a_token(browser: TestClient, server: FakeJmap) -> None:
    browser.app.state.services = replace(  # type: ignore[attr-defined]
        browser.app.state.services,  # type: ignore[attr-defined]
        discovery=NothingFound(),
    )
    page = post(browser, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert "over JMAP, IMAP or POP3 was found" in page
    assert "Set up a JMAP server by hand" in page
    assert 'name="provider" value="jmap"' in page
    done = post(
        browser,
        "/ui/accounts",
        {
            "email": "me@example.org",
            "provider": "jmap",
            "host": HOST,
            "auth": "token",
            "password": TOKEN,
        },
    )
    assert done.status_code == 200, done.text
    assert "me@example.org connected" in done.text
    assert server.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    # The token is stored as one, and the account page asks for a new one.
    assert "token" in done.text and "New API token" in done.text


def test_a_refused_token_shows_the_form_again(browser: TestClient) -> None:
    done = post(
        browser,
        "/ui/accounts",
        {
            "email": "me@example.org",
            "provider": "jmap",
            "host": HOST,
            "auth": "token",
            "password": "wrong",
        },
    )
    assert done.status_code == 502, done.status_code
    assert "API token" in done.text and "JMAP server" in done.text
    assert "wrong" not in done.text


class FoundJmap:
    """Discovery without the network: a JMAP server that wants a token."""

    async def discover(self, caller: Any, email: str) -> Discovery:
        return Discovery(
            email=email,
            domain="example.org",
            candidates=[
                Candidate(
                    provider=ProviderType.JMAP,
                    name="Fastmail",
                    credential="api_token",
                    source="preset",
                    confirmed=True,
                    settings={
                        "host": "api.example.org",
                        "port": 443,
                        "path": "/jmap/session",
                        "auth": "token",
                    },
                )
            ],
        )


def test_a_discovered_jmap_server(browser: TestClient) -> None:
    browser.app.state.services = replace(  # type: ignore[attr-defined]
        browser.app.state.services,  # type: ignore[attr-defined]
        discovery=FoundJmap(),
    )
    page = post(browser, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert 'name="provider" value="jmap"' in page
    assert ">API token<" in page and 'value="/jmap/session"' in page
    assert '<option value="token" selected>' in page


# --- a draft that gets a new id when it is replaced -----------------------------------


def saved_draft(browser: TestClient, account_id: str) -> str:
    saved = post(
        browser,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "subject": "Plan", "text": "first", "do": "save"},
    )
    assert "Draft saved." in saved.text
    return saved.url.path


def test_a_draft_edited_and_sent(
    browser: TestClient, account_id: str, server: FakeJmap
) -> None:
    first = saved_draft(browser, account_id)
    edited = post(
        browser,
        first,
        {"to": "bob@example.org", "subject": "Plan", "text": "second", "do": "save"},
    )
    assert "Draft saved." in edited.text and "second" in edited.text
    second = edited.url.path
    assert second != first and browser.get(first).status_code == 404
    sent = post(
        browser,
        second,
        {"to": "bob@example.org", "subject": "Plan", "text": "third", "do": "send"},
    )
    assert "Sent." in sent.text, sent.text
    [submission] = server.submissions
    assert b"third" in server.raw_of(submission["emailId"])
    assert submission["envelope"]["rcptTo"] == [{"email": "bob@example.org"}]


def test_a_draft_saved_but_not_sent(
    browser: TestClient, account_id: str, server: FakeJmap
) -> None:
    first = saved_draft(browser, account_id)
    server.refuse_submission = {"type": "forbiddenToSend", "description": "quota"}
    refused = post(
        browser,
        first,
        {"to": "bob@example.org", "subject": "Plan", "text": "second", "do": "send"},
    )
    assert refused.status_code == 409 and "quota" in refused.text
    [now] = [
        e["id"]
        for e in server.emails.values()
        if "drafts" in e["mailboxIds"] and b"second" in server.raw_of(e["id"])
    ]
    # The form goes on with the draft as it is stored now.
    assert f'action="/ui/accounts/{account_id}/drafts/{now}"' in refused.text
