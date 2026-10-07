"""Mails written as HTML: both parts, the text part made from the HTML."""

from __future__ import annotations

from datetime import UTC, datetime
from email import message_from_bytes
from email.policy import default

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.mail import compose
from benethos_mailbox_service.data.models import OutgoingMessage, Recipient
from benethos_mailbox_service.data.providers.memory import MemoryProvider


def parts(raw: bytes) -> tuple[str, str]:
    mail = message_from_bytes(raw, policy=default)
    assert mail.get_content_type() == "multipart/alternative"
    return (
        mail.get_body(("plain",)).get_content().strip(),
        mail.get_body(("html",)).get_content().strip(),
    )


def compose_(message: OutgoingMessage) -> bytes:
    return compose.message(
        message,
        Recipient(email="me@example.com"),
        datetime(2026, 9, 24, tzinfo=UTC),
        "<id@example.com>",
    )


def test_html_only_gets_a_text_part() -> None:
    raw = compose_(
        OutgoingMessage(
            to=[Recipient(email="bob@example.org")], html="<p>Hi <b>Bob</b></p>"
        )
    )
    assert parts(raw) == ("Hi Bob", "<p>Hi <b>Bob</b></p>")


def test_a_given_text_part_is_kept() -> None:
    raw = compose_(
        OutgoingMessage(
            to=[Recipient(email="bob@example.org")], text="Hello", html="<p>Hi</p>"
        )
    )
    assert parts(raw)[0] == "Hello"


def test_a_reply_in_html_quotes_the_html_as_text(
    client: TestClient, services: Services, account_id: str
) -> None:
    first = client.get(f"/v1/accounts/{account_id}/messages").json()["items"][0]
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={
            "html": "<p>Thanks, <i>paid</i></p>",
            "reference": {"message_id": first["id"], "action": "reply"},
        },
    )
    assert answer.status_code == 200
    provider = services.adapters.get(account_id)
    assert isinstance(provider, MemoryProvider)
    [(_, _, raw)] = provider.outbox
    text, html = parts(raw)
    assert text.startswith("Thanks, paid")
    assert "> body" in text  # the quote of the original
    assert html.startswith("<p>Thanks, <i>paid</i></p>")
