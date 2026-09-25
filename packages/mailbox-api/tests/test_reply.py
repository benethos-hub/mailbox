"""Reply and forward by reference (CONCEPT 6.4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.mail import compose
from benethos_mailbox_api.data.models import (
    Address,
    Grant,
    Message,
    MessageReference,
    OutgoingMessage,
    ProviderType,
    Recipient,
)
from benethos_mailbox_api.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_api.data.providers.imap import ImapProvider
from benethos_mailbox_api.data.providers.protocols.imap import ImapSession
from benethos_mailbox_api.data.providers.protocols.smtp import SmtpSession
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.main import Services, build_services, create_app

from .conftest import ADMIN, bearer_for, create_account
from .imap_fake import FakeFolder, FakeMailBox, make_message
from .smtp_fake import FakeSmtpServer

ORIGINAL = Message(
    id="m1",
    subject="Angebot",
    sender=Address(email="alice@example.com", name="Alice"),
    to=[Address(email="me@example.com")],
    date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    text_body="Line one\n\nLine three",
    html_body=None,
)

# --- formatting, pure -------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "expected"),
    [("Angebot", "Re: Angebot"), ("RE: Angebot", "RE: Angebot"), (None, "Re:")],
)
def test_prefixed(subject: str | None, expected: str) -> None:
    assert compose.prefixed("Re:", subject) == expected


def test_references_carry_the_chain() -> None:
    raw = b"Message-ID: <3@x>\r\nReferences: <1@x> <2@x>\r\n\r\nbody"
    assert compose.references(raw) == ("<3@x>", ("<1@x>", "<2@x>", "<3@x>"))


def test_references_from_in_reply_to_alone() -> None:
    raw = b"Message-ID: <3@x>\r\nIn-Reply-To: <2@x>\r\n\r\nbody"
    assert compose.references(raw) == ("<3@x>", ("<2@x>", "<3@x>"))


def test_a_quote() -> None:
    text = compose.quoted(ORIGINAL, "Gern.")
    assert text == (
        "Gern.\n\nOn Tue, 01 Sep 2026 10:00:00 +0000, Alice <alice@example.com> "
        "wrote:\n> Line one\n>\n> Line three\n"
    )


def test_a_forward_block() -> None:
    text = compose.forwarded(ORIGINAL, "FYI")
    assert "---------- Forwarded message ----------" in text
    assert "From: Alice <alice@example.com>" in text
    assert "Subject: Angebot" in text
    assert text.endswith("Line one\n\nLine three\n")


def test_quoted_html_escapes_plain_text() -> None:
    original = ORIGINAL.model_copy(update={"text_body": "<script>x</script>"})
    html = compose.quoted_html(original, "<p>Hi</p>", "Original message")
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


# --- through the service, against fake IMAP and SMTP servers ------------------------


@pytest.fixture
def smtp() -> FakeSmtpServer:
    return FakeSmtpServer()


@pytest.fixture
def box() -> FakeMailBox:
    box = FakeMailBox()
    box.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    box.add(
        "INBOX",
        1,
        make_message(
            "Angebot",
            sender="Alice <alice@example.com>",
            to="me@example.com, bob@example.com",
            extra_headers={"Cc": "carol@example.com, me@example.com"},
            attachments=[("offer.pdf", "application/pdf", b"%PDF")],
        ),
    )
    return box


@pytest.fixture
def services(
    box: FakeMailBox, smtp: FakeSmtpServer, monkeypatch: pytest.MonkeyPatch
) -> Services:
    monkeypatch.setenv("MAILBOX_API_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> ImapProvider:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=box),
            smtp_factory=lambda server: SmtpSession(server, connection_factory=smtp),
            sleep=lambda seconds: None,
        )

    services = build_services(
        Settings(storage="memory", api_key=SecretStr("k")), provider_factory=factory
    )
    services.vault.initialize()
    return services


@pytest.fixture
def account_id(services: Services) -> str:
    return create_account(
        services.accounts,
        ProviderType.IMAP,
        "me@example.com",
        settings={
            "host": "imap.example.com",
            "username": "me@example.com",
            "smtp_host": "smtp.example.com",
        },
        credentials={"password": SecretStr("secret")},
    ).id


async def original_id(services: Services, account_id: str) -> str:
    page = await services.mailbox.list_messages(
        ADMIN, account_id, folder_id=None, search=None, limit=5, cursor=None
    )
    return page.items[0].id


Sender = Callable[..., Awaitable[EmailMessage]]


@pytest.fixture
def send(services: Services, smtp: FakeSmtpServer, account_id: str) -> Sender:
    """Send through the service; the message as the SMTP server got it."""

    async def run(reference: MessageReference, **fields: object) -> EmailMessage:
        await services.mailbox.send_message(
            ADMIN,
            account_id,
            OutgoingMessage.model_validate({"reference": reference, **fields}),
        )
        mail = message_from_bytes(smtp.sent[-1].raw, policy=default)
        assert isinstance(mail, EmailMessage)
        return mail

    return run


def plain(mail: EmailMessage) -> str:
    """The text part, with the line ends a reader sees."""
    part = mail.get_body(("plain",))
    assert part is not None
    return str(part.get_content()).replace("\r\n", "\n")


async def test_reply(
    send: Sender, services: Services, account_id: str, box: FakeMailBox
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(message_id=message_id, action="reply"),
        text="Danke!",
    )
    original_header = f"<{abs(hash('Angebot'))}@example.com>"
    assert mail["To"] == "Alice <alice@example.com>"
    assert mail["Cc"] is None
    assert mail["Subject"] == "Re: Angebot"
    assert mail["In-Reply-To"] == original_header
    assert mail["References"] == original_header
    body = plain(mail)
    assert body.startswith("Danke!\n\nOn ")
    assert "> Hello" in body
    # The original is marked answered, for other mail clients too.
    assert "\\Answered" in box.folders["INBOX"].messages[1][1]


async def test_reply_all_leaves_out_this_account(
    send: Sender, smtp: FakeSmtpServer, services: Services, account_id: str
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(message_id=message_id, action="reply_all"),
    )
    assert mail["To"] == "Alice <alice@example.com>"
    assert mail["Cc"] == "bob@example.com, carol@example.com"
    recipients = smtp.sent[-1].recipients
    assert "me@example.com" not in recipients


async def test_named_recipients_win(
    send: Sender, services: Services, account_id: str
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(message_id=message_id, action="reply"),
        to=[Recipient(email="dave@example.com")],
        subject="Eigener Betreff",
    )
    assert mail["To"] == "dave@example.com"
    assert mail["Subject"] == "Eigener Betreff"


async def test_forward_inline_with_the_attachments(
    send: Sender, services: Services, account_id: str, box: FakeMailBox
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(message_id=message_id, action="forward"),
        to=[Recipient(email="dave@example.com")],
        text="Zur Info",
    )
    assert mail["Subject"] == "Fwd: Angebot"
    assert mail["In-Reply-To"] is None
    body = plain(mail)
    assert "---------- Forwarded message ----------" in body
    [attachment] = list(mail.iter_attachments())
    assert attachment.get_filename() == "offer.pdf"
    assert attachment.get_content() == b"%PDF"
    assert "$Forwarded" in box.folders["INBOX"].messages[1][1]


async def test_forward_as_attachment(
    send: Sender, services: Services, account_id: str
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(
            message_id=message_id, action="forward", forward_as="attachment"
        ),
        to=[Recipient(email="dave@example.com")],
    )
    [attached] = list(mail.iter_attachments())
    assert attached.get_content_type() == "message/rfc822"
    inner = attached.get_content()
    assert inner["Subject"] == "Angebot"


def test_a_forward_needs_recipients() -> None:
    with pytest.raises(ValueError, match="recipient"):
        OutgoingMessage(reference=MessageReference(message_id="m", action="forward"))


def test_answering_needs_the_right_to_read(services: Services, account_id: str) -> None:
    client = TestClient(create_app(Settings(storage="memory"), services))

    message_id = anyio.run(original_id, services, account_id)
    only_send = bearer_for(services, Grant(accounts=[account_id], allow=["send"]))
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"reference": {"message_id": message_id, "action": "reply"}},
        headers=only_send,
    )
    assert answer.status_code == 403
    assert "get_message" in answer.json()["error"]["message"]
    both = bearer_for(
        services, Grant(accounts=[account_id], allow=["send", "mail.read"])
    )
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"reference": {"message_id": message_id, "action": "reply"}},
        headers=both,
    )
    assert answer.status_code == 200


async def test_a_reply_without_quote_keeps_the_thread(
    send: Sender, services: Services, account_id: str, box: FakeMailBox
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(message_id=message_id, action="reply", quote=False),
        text="Danke!\n\n> quoted before",
    )
    assert mail["Subject"] == "Re: Angebot"
    assert mail["In-Reply-To"] == f"<{abs(hash('Angebot'))}@example.com>"
    assert plain(mail) == "Danke!\n\n> quoted before\n"
    assert "\\Answered" in box.folders["INBOX"].messages[1][1]


async def test_a_forward_without_quote_adds_nothing_of_the_original(
    send: Sender, services: Services, account_id: str
) -> None:
    message_id = await original_id(services, account_id)
    mail = await send(
        MessageReference(message_id=message_id, action="forward", quote=False),
        to=[Recipient(email="dave@example.com")],
        text="Mine",
    )
    assert mail["Subject"] == "Fwd: Angebot"
    assert "Forwarded message" not in plain(mail)
    assert list(mail.iter_attachments()) == []
