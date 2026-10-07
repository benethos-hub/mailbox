"""Sending (CONCEPT 6.4): composing, SMTP, the copy in the sent folder."""

from __future__ import annotations

import base64
import imaplib
from datetime import UTC, datetime
from email import message_from_bytes
from email.policy import default

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.mail import compose
from benethos_mailbox_service.data.models import (
    Grant,
    OutgoingMessage,
    ProviderType,
    Recipient,
)
from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.protocols.smtp import SmtpSession
from benethos_mailbox_service.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_service.domain.mailbox import checks
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    ProviderAuthError,
)

from ...conftest import bearer_for, memory_of
from ...imap_fake import FakeFolder, FakeMailBox
from ...smtp_fake import FakeSmtpServer

MESSAGE = OutgoingMessage(
    to=[Recipient(email="you@example.com", name="Jürgen Müller")],
    cc=[Recipient(email="cc@example.com")],
    bcc=[Recipient(email="hidden@example.com")],
    subject="Grüße",
    text="Hallo",
    html="<p>Hallo</p>",
    attachments=[
        {
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "data": "JVBERg==",
        }  # %PDF
    ],
)
SENDER = Recipient(email="me@example.com", name="Me")

# --- composing ----------------------------------------------------------------------


def test_compose() -> None:
    raw = compose.message(
        MESSAGE, SENDER, datetime(2026, 9, 24, 12, 0, tzinfo=UTC), "<id@example.com>"
    )
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    mail = message_from_bytes(raw, policy=default)
    assert mail["From"] == "Me <me@example.com>"
    assert mail["To"] == "Jürgen Müller <you@example.com>"
    assert mail["Cc"] == "cc@example.com"
    assert "Bcc" not in mail and b"hidden@example.com" not in raw
    assert mail["Subject"] == "Grüße"
    assert mail["Date"] == "Thu, 24 Sep 2026 12:00:00 +0000"
    assert mail["Message-ID"] == "<id@example.com>"
    assert mail.get_body(("plain",)).get_content().strip() == "Hallo"
    # Sent without 8BITMIME, so the bytes stay ASCII.
    assert raw.isascii()
    assert mail.get_body(("html",)).get_content().strip() == "<p>Hallo</p>"
    [attachment] = list(mail.iter_attachments())
    assert attachment.get_filename() == "a.pdf"
    assert attachment.get_content() == b"%PDF"


def test_a_message_id_in_the_sender_domain() -> None:
    assert compose.new_message_id("me@example.com").endswith("@example.com>")
    assert compose.new_message_id("me@bücher.example").endswith(
        "@xn--bcher-kva.example>"
    )


def test_an_international_domain_goes_in_punycode() -> None:
    message = OutgoingMessage(
        to=[Recipient(email="du@bücher.example", name="Dü")], text="Hallo"
    )
    sender = Recipient(email="me@münchen.example")
    raw = compose.message(message, sender, datetime(2026, 9, 24, tzinfo=UTC), "<i@x>")
    assert raw.isascii()
    mail = message_from_bytes(raw, policy=default)
    assert mail["From"] == "me@xn--mnchen-3ya.example"
    assert mail["To"] == "Dü <du@xn--bcher-kva.example>"


def test_a_local_part_beyond_ascii_makes_a_message_for_smtputf8() -> None:
    message = OutgoingMessage(to=[Recipient(email="dü@bücher.example")], text="Hallo")
    raw = compose.message(
        message, SENDER, datetime(2026, 9, 24, tzinfo=UTC), "<i@example.com>"
    )
    # UTF-8 in the header: an encoded word is not allowed in an address.
    assert "To: dü@xn--bcher-kva.example\r\n".encode() in raw
    assert b"=?utf-8?" not in raw.partition(b"\r\n\r\n")[0]


def test_an_address_whose_domain_cannot_be_encoded() -> None:
    message = OutgoingMessage(to=[Recipient(email="du@bü.example")], text="x")
    with pytest.raises(BadRequestError, match="cannot be encoded"):
        compose.message(
            message,
            Recipient(email="me@" + "ü" * 70 + ".example"),
            datetime(2026, 9, 24, tzinfo=UTC),
            "<i@x>",
        )


def test_recipients_each_once() -> None:
    message = OutgoingMessage(
        to=[Recipient(email="a@x.de")], bcc=[Recipient(email="a@x.de")]
    )
    assert message.recipients() == ["a@x.de"]


# --- the IMAP adapter -----------------------------------------------------------------


@pytest.fixture
def box() -> FakeMailBox:
    box = FakeMailBox()
    box.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    return box


def adapter(box: FakeMailBox, smtp: FakeSmtpServer, **settings: object) -> ImapProvider:
    return ImapProvider(
        {
            "host": "imap.example.com",
            "username": "me@example.com",
            "smtp_host": "smtp.example.com",
            **settings,
        },
        lambda field: SecretStr("secret"),
        session_factory=lambda s: ImapSession(s, client_factory=box),
        smtp_factory=lambda server: SmtpSession(server, connection_factory=smtp),
    )


RAW = compose.message(MESSAGE, SENDER, datetime.now(UTC), "<one@example.com>")
TO = ["you@example.com", "cc@example.com", "hidden@example.com"]


async def test_send_and_keep_a_read_copy(box: FakeMailBox) -> None:
    smtp = FakeSmtpServer()
    sent = await adapter(box, smtp).send(RAW, "me@example.com", TO)
    assert smtp.sent[0].recipients == TO
    assert smtp.sent[0].raw == RAW
    assert sent.sent_copy is not None
    assert sent.sent_copy.folder_ids == [mappers.folder_id("Sent")]
    assert sent.sent_copy.unread is False
    [(uid, (_, flags))] = box.folders["Sent"].messages.items()
    assert sent.sent_copy.id == mappers.message_id("Sent", 1, uid)
    assert flags == ("\\Seen",)


async def test_without_appenduid_found_by_message_id(box: FakeMailBox) -> None:
    box.copyuid = False
    sent = await adapter(box, FakeSmtpServer()).send(RAW, "me@example.com", TO)
    assert sent.sent_copy is not None


async def test_a_failed_copy_does_not_fail_the_send(
    box: FakeMailBox, caplog: pytest.LogCaptureFixture
) -> None:
    box.append_failure = imaplib.IMAP4.error("over quota")
    smtp = FakeSmtpServer()
    sent = await adapter(box, smtp).send(RAW, "me@example.com", TO)
    assert len(smtp.sent) == 1
    assert sent.sent_copy is None
    # The adapter reports it, the domain logs it.
    assert sent.copy_error is not None and "over quota" in sent.copy_error
    assert not caplog.records


async def test_no_sent_folder_no_copy() -> None:
    sent = await adapter(FakeMailBox(), FakeSmtpServer()).send(
        RAW, "me@example.com", TO
    )
    assert sent.sent_copy is None


async def test_no_smtp_server_no_sending(box: FakeMailBox) -> None:
    provider = adapter(box, FakeSmtpServer(), smtp_host="")
    with pytest.raises(ConflictError, match="smtp_host"):
        await provider.send(RAW, "me@example.com", TO)


async def test_a_rejected_login_stops_further_attempts(box: FakeMailBox) -> None:
    smtp = FakeSmtpServer(password="other")
    provider = adapter(box, smtp)
    with pytest.raises(ProviderAuthError):
        await provider.send(RAW, "me@example.com", TO)
    connects = len([c for c in smtp.calls if c[0] == "connect"])
    with pytest.raises(ProviderAuthError, match="before"):
        await provider.send(RAW, "me@example.com", TO)
    assert len([c for c in smtp.calls if c[0] == "connect"]) == connects


# --- the API ------------------------------------------------------------------------


def body() -> dict[str, object]:
    return {
        "to": [{"email": "you@example.com"}],
        "bcc": [{"email": "hidden@example.com"}],
        "subject": "Test",
        "text": "Hallo",
        "attachments": [
            {"filename": "a.txt", "data": base64.b64encode(b"data").decode()}
        ],
    }


def test_send(client: TestClient, services: Services, account_id: str) -> None:
    answer = client.post(f"/v1/accounts/{account_id}/send", json=body())
    assert answer.status_code == 200
    result = answer.json()
    assert result["refused"] == []
    assert result["sent_copy_id"]
    [(sender, recipients, raw)] = memory_of(services, account_id).outbox
    assert sender == "me@example.com"
    assert recipients == ["you@example.com", "hidden@example.com"]
    mail = message_from_bytes(raw, policy=default)
    assert mail["From"] == "me@example.com"
    assert mail["Message-ID"] == result["message_id_header"]
    assert mail["Date"] is not None
    assert "Bcc" not in mail


def test_a_display_name_stored_with_a_line_break_sends_on_one_line(
    client: TestClient, services: Services, account_id: str
) -> None:
    """One stored before names were checked."""
    stored = services.repositories.accounts
    account = stored.get(account_id)
    broken = account.model_copy(update={"display_name": "Me\r\nBcc: x@example.org"})
    stored.update(broken, stored.settings(account_id))
    answer = client.post(f"/v1/accounts/{account_id}/send", json=body())
    assert answer.status_code == 200, answer.text
    [(_, recipients, raw)] = memory_of(services, account_id).outbox
    assert "x@example.org" not in recipients
    mail = message_from_bytes(raw, policy=default)
    assert mail["From"] == '"Me Bcc: x@example.org" <me@example.com>'
    assert "Bcc" not in mail


@pytest.mark.parametrize(
    "change",
    [
        {"subject": "Hi\r\nBcc: someone@else.example"},
        {"to": [{"email": "not an address"}]},
    ],
)
def test_send_refuses_bad_messages(
    client: TestClient, account_id: str, change: dict[str, object]
) -> None:
    answer = client.post(f"/v1/accounts/{account_id}/send", json={**body(), **change})
    assert answer.status_code == 422


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"to": [], "bcc": []}, "at least one recipient"),
        (
            {"to": [{"email": f"r{n}@example.com"} for n in range(101)]},
            "at most 100 recipients",
        ),
    ],
)
def test_send_refuses_what_the_service_does_not_carry(
    client: TestClient, account_id: str, change: dict[str, object], reason: str
) -> None:
    answer = client.post(f"/v1/accounts/{account_id}/send", json={**body(), **change})
    assert answer.status_code == 400
    assert reason in answer.json()["error"]["message"]


def test_attachments_have_a_size_limit(
    client: TestClient, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checks, "MAX_ATTACHMENT_BYTES", 3)
    answer = client.post(f"/v1/accounts/{account_id}/send", json=body())
    assert answer.status_code == 400
    assert "the attachments exceed" in answer.json()["error"]["message"]


def test_sending_is_its_own_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/send"
    writer = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.write"])
    )
    assert app_client.post(url, json=body(), headers=writer).status_code == 403
    sender = bearer_for(services, Grant(accounts=[account_id], allow=["send"]))
    assert app_client.post(url, json=body(), headers=sender).status_code == 200
    assert memory_of(services, account_id).outbox


def test_the_account_kind_is_memory(services: Services, account_id: str) -> None:
    assert services.adapters.record(account_id).provider is ProviderType.MEMORY
