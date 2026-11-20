"""Sending over IMAP and SMTP: the message goes out, a read copy is kept
in the sent folder, found by its Message-ID without APPENDUID, and a
failed copy or a missing folder does not fail the send."""

from __future__ import annotations

import imaplib
from datetime import UTC, datetime

import pytest

from benethos_mailbox_service.data.mail import compose
from benethos_mailbox_service.data.models import (
    OutgoingMessage,
    Recipient,
)
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import (
    NotSupportedError,
    ProviderAuthError,
)

from ...imap_adapter import sending
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


# --- the IMAP adapter -----------------------------------------------------------------


@pytest.fixture
def sending_box() -> FakeMailBox:
    sending_box = FakeMailBox()
    sending_box.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    return sending_box


RAW = compose.message(MESSAGE, SENDER, datetime.now(UTC), "<one@example.com>")
TO = ["you@example.com", "cc@example.com", "hidden@example.com"]


async def test_send_and_keep_a_read_copy(sending_box: FakeMailBox) -> None:
    smtp = FakeSmtpServer()
    sent = await sending(sending_box, smtp).send(RAW, "me@example.com", TO)
    assert smtp.sent[0].recipients == TO
    assert smtp.sent[0].raw == RAW
    assert sent.sent_copy is not None
    assert sent.sent_copy.folder_ids == [mappers.folder_id("Sent")]
    assert sent.sent_copy.unread is False
    [(uid, (_, flags))] = sending_box.folders["Sent"].messages.items()
    assert sent.sent_copy.id == mappers.message_id("Sent", 1, uid)
    assert flags == ("\\Seen",)


async def test_without_appenduid_found_by_message_id(sending_box: FakeMailBox) -> None:
    sending_box.copyuid = False
    sent = await sending(sending_box, FakeSmtpServer()).send(RAW, "me@example.com", TO)
    assert sent.sent_copy is not None


async def test_a_failed_copy_does_not_fail_the_send(
    sending_box: FakeMailBox, caplog: pytest.LogCaptureFixture
) -> None:
    sending_box.append_failure = imaplib.IMAP4.error("over quota")
    smtp = FakeSmtpServer()
    sent = await sending(sending_box, smtp).send(RAW, "me@example.com", TO)
    assert len(smtp.sent) == 1
    assert sent.sent_copy is None
    # The adapter reports it, the domain logs it.
    assert sent.copy_error is not None and "over quota" in sent.copy_error
    assert not caplog.records


async def test_no_sent_folder_no_copy() -> None:
    sent = await sending(FakeMailBox(), FakeSmtpServer()).send(
        RAW, "me@example.com", TO
    )
    assert sent.sent_copy is None


async def test_no_smtp_server_no_sending(sending_box: FakeMailBox) -> None:
    provider = sending(sending_box, FakeSmtpServer(), smtp_host="")
    with pytest.raises(NotSupportedError, match="smtp_host"):
        await provider.send(RAW, "me@example.com", TO)


async def test_a_rejected_login_stops_further_attempts(
    sending_box: FakeMailBox,
) -> None:
    smtp = FakeSmtpServer(password="other")
    provider = sending(sending_box, smtp)
    with pytest.raises(ProviderAuthError):
        await provider.send(RAW, "me@example.com", TO)
    connects = len([c for c in smtp.calls if c[0] == "connect"])
    with pytest.raises(ProviderAuthError, match="before"):
        await provider.send(RAW, "me@example.com", TO)
    assert len([c for c in smtp.calls if c[0] == "connect"]) == connects
