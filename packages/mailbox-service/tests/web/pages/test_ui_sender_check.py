"""The receiving server's check of a sender, on the page of a message,
in a list and on the page of an account."""

from __future__ import annotations

import html

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    SenderCheck,
)
from benethos_mailbox_service.web.pages.sender import sender_tag

from ...conftest import memory_of

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
