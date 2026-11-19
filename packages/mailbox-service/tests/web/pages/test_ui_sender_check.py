"""The receiving server's check of a sender, on the page of a message,
in a list and on the page of an account."""

from __future__ import annotations

import html
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    Abilities,
    Account,
    Capability,
    Grant,
    ProviderType,
    SenderCheck,
)
from benethos_mailbox_service.domain.accounts import SeenName, SeenNames
from benethos_mailbox_service.web.pages.sender import sender_tag

from ...conftest import browser_user, memory_of, relearn
from ...ui_helpers import sign_in

PASSED = SenderCheck(
    result="pass", domain="example.com", matches_from=True, method="dmarc"
)
FAILED = SenderCheck(
    result="fail", domain="example.com", matches_from=True, method="dmarc"
)
UNKNOWN = SenderCheck(result="unknown", reason="no_entry")


def checked(services: Services, account_id: str, check: SenderCheck) -> None:
    """Every message of the account carries ``check``."""
    for message in memory_of(services, account_id).messages:
        message.sender_check = check


@pytest.mark.parametrize(
    ("check", "tag"),
    [
        (
            PASSED,
            '<span class="tag ok" title="The receiving server confirmed '
            'the domain in From by dmarc.">checked: example.com</span>',
        ),
        (
            FAILED,
            '<span class="tag bad" title="The receiving server&#39;s check '
            'of the domain in From failed.">check failed</span>',
        ),
        (
            UNKNOWN,
            '<span class="tag" title="The receiving server wrote no check '
            'into this mail.">not checked</span>',
        ),
    ],
)
def test_a_message_shows_its_sender_check(
    ui: TestClient,
    services: Services,
    account_id: str,
    check: SenderCheck,
    tag: str,
) -> None:
    checked(services, account_id, check)
    page = ui.get(f"/ui/accounts/{account_id}/mail/m1").text
    assert tag in page


def test_another_domain_is_named() -> None:
    other = SenderCheck(
        result="unknown",
        domain="example.net",
        matches_from=False,
        method="dkim",
        reason="other_domain",
    )
    found = sender_tag(other)
    assert (found.text, found.cls) == ("not checked", "")
    assert found.title == "The server checked another domain: example.net."


@pytest.mark.parametrize(("check", "count"), [(PASSED, 0), (UNKNOWN, 0), (FAILED, 1)])
def test_a_list_names_a_failed_check_alone(
    ui: TestClient,
    services: Services,
    account_id: str,
    check: SenderCheck,
    count: int,
) -> None:
    memory = memory_of(services, account_id)
    for message in memory.messages:
        message.sender_check = UNKNOWN
    memory.messages[0].sender_check = check
    page = html.unescape(ui.get(f"/ui/accounts/{account_id}/mail").text)
    assert page.count("check failed") == count
    assert "checked: example.com" not in page


def test_the_account_page_names_the_capability_and_the_field(
    ui: TestClient, services: Services, account_id: str
) -> None:
    memory = memory_of(services, account_id)
    memory.given = Abilities.of({Capability.SENDER_CHECK})
    relearn(services, account_id)
    page = ui.get(f"/ui/accounts/{account_id}").text
    assert '<span class="tag">sender check</span>' in page
    assert 'id="f-authserv_id"' in page


def test_a_gmail_account_takes_no_name_of_its_server(
    ui: TestClient, services: Services
) -> None:
    services.repositories.accounts.add(
        Account(id="acc_gmail", provider=ProviderType.GMAIL, email="g@example.com")
    )
    page = ui.get("/ui/accounts/acc_gmail").text
    assert "authserv_id" not in page


# --- the names in the newest mails ----------------------------------------------------


NONE_READ = SeenNames(0, ())


def asked(
    services: Services,
    monkeypatch: pytest.MonkeyPatch,
    found: SeenNames = NONE_READ,
) -> list[str]:
    """The account service answers ``found``, and notes each account asked."""
    calls: list[str] = []

    async def server_names(access: Any, account_id: str) -> SeenNames:
        calls.append(account_id)
        return found

    monkeypatch.setattr(services.accounts, "server_names", server_names)
    return calls


def test_the_page_reads_the_mailbox_only_when_asked(
    ui: TestClient,
    services: Services,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = asked(
        services, monkeypatch, SeenNames(10, (SeenName("mx.example.org", 9, 9),))
    )
    page = ui.get(f"/ui/accounts/{account_id}").text
    assert calls == []
    assert f'href="/ui/accounts/{account_id}?suggest=1"' in page
    shown = ui.get(f"/ui/accounts/{account_id}", params={"suggest": "1"}).text
    assert calls == [account_id]
    assert "Seen in the newest 10 mails:" in shown
    assert '<code id="seen-1">mx.example.org</code>' in shown
    assert 'data-copy="seen-1"' in shown
    assert "9 of 10" in shown
    assert "A mail can carry any name." in shown


def test_no_name_in_the_newest_mails(ui: TestClient, account_id: str) -> None:
    """The memory adapter reads no names, as a server that writes none."""
    page = ui.get(f"/ui/accounts/{account_id}", params={"suggest": "1"}).text
    assert "No Authentication-Results in the newest mails" in page


def test_a_gmail_account_is_not_offered_it(
    ui: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = asked(services, monkeypatch)
    services.repositories.accounts.add(
        Account(id="acc_gmail", provider=ProviderType.GMAIL, email="g@example.com")
    )
    page = ui.get("/ui/accounts/acc_gmail", params={"suggest": "1"}).text
    assert "Look in the mailbox" not in page
    assert calls == []


def test_a_reader_is_not_offered_it(
    app_client: TestClient,
    services: Services,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = asked(services, monkeypatch)
    sign_in(
        app_client,
        *browser_user(
            services,
            Grant(accounts=[account_id], allow=["list_accounts", "get_account"]),
        ),
    )
    page = app_client.get(f"/ui/accounts/{account_id}", params={"suggest": "1"}).text
    assert "Look in the mailbox" not in page and "Seen in the newest" not in page
    assert calls == []
