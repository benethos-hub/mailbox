"""The outbox when the outcome of a send cannot be told: a connection
that drops once the server took the message, a service that stopped
while sending. Found in the sent folder, it went out. Where the account
cannot look, it is never sent again. Else it is looked for once more
after a while, and only then sent anew. Never twice."""

from __future__ import annotations

import asyncio
import smtplib
from datetime import timedelta

import httpx
import pytest

from benethos_mailbox_service.data.models import Message, SentMessage
from benethos_mailbox_service.data.protocols.http.base import unreachable
from benethos_mailbox_service.data.protocols.smtp import (
    Server,
    SmtpLogin,
    SmtpSession,
)
from benethos_mailbox_service.domain.mailbox.outgoing import queued
from benethos_mailbox_service.errors import (
    NotSupportedError,
    OutcomeUnknownError,
    ProviderUnavailableError,
)

from ....smtp_fake import FakeSmtpServer
from .outbox_helpers import Outbox, build

LOGIN = SmtpLogin("me@example.com", "secret")


def smtp_send(fake: FakeSmtpServer) -> list[str]:
    session = SmtpSession(
        Server("smtp.example.com", 465, "tls"), connection_factory=fake
    )
    return session.send(LOGIN, "me@example.com", ["bob@example.org"], b"Hi.\r\n")


def test_a_drop_while_the_server_takes_the_message_is_unclear() -> None:
    fake = FakeSmtpServer(data_failure=smtplib.SMTPServerDisconnected("gone"))
    with pytest.raises(OutcomeUnknownError) as raised:
        smtp_send(fake)
    assert raised.value.code == "provider_unavailable"


def test_a_failure_before_data_sent_nothing() -> None:
    fake = FakeSmtpServer(failure=OSError("refused"))
    with pytest.raises(ProviderUnavailableError) as raised:
        smtp_send(fake)
    assert not isinstance(raised.value, OutcomeUnknownError)


@pytest.mark.parametrize(
    ("error", "unclear"),
    [
        (httpx.ReadTimeout("slow"), True),
        (httpx.ReadError("cut"), True),
        (httpx.RemoteProtocolError("broken"), True),
        (httpx.ConnectError("refused"), False),
        (httpx.ConnectTimeout("slow"), False),
    ],
)
def test_an_http_failure_after_sending_is_unclear(
    error: httpx.HTTPError, unclear: bool
) -> None:
    found = unreachable(error, "api.example.org")
    assert isinstance(found, OutcomeUnknownError) is unclear
    assert found.code == "provider_unavailable"


@pytest.fixture
def box(messages: list[Message]) -> Outbox:
    return build(messages)


def unclear_once(box: Outbox, *, goes_out: bool) -> None:
    """The provider's next send ends unclear: having sent, or not."""
    provider = box.memory()
    real = provider.send
    calls = 0

    async def send(raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        nonlocal calls
        calls += 1
        if calls > 1:
            return await real(raw, sender, recipients)
        if goes_out:
            await real(raw, sender, recipients)
        raise OutcomeUnknownError("no answer")

    provider.send = send  # type: ignore[method-assign]


def test_an_unclear_send_found_in_the_sent_folder_went_out(box: Outbox) -> None:
    unclear_once(box, goes_out=True)
    job = box.queue()
    box.round()
    done = box.job(job.id)
    assert done.state == "sent" and len(box.sent()) == 1
    assert box.drafts() == []
    assert ("sent", None) in box.outcomes()
    box.clock.tick(hours=1)
    box.round()
    assert len(box.sent()) == 1


def test_an_unclear_send_not_found_is_sent_once_more_later(box: Outbox) -> None:
    unclear_once(box, goes_out=False)
    job = box.queue()
    box.round()
    waiting = box.job(job.id)
    assert (waiting.state, waiting.unclear_since) == ("queued", box.clock.now)
    assert waiting.due_at == box.clock.now + timedelta(minutes=15)
    box.clock.tick(minutes=14)
    box.round()
    assert box.sent() == []
    box.clock.tick(minutes=1)
    box.round()
    done = box.job(job.id)
    assert (done.state, done.unclear_since) == ("sent", None)
    assert len(box.sent()) == 1


def test_where_the_account_cannot_look_it_is_never_sent_again(
    box: Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cannot(_: object) -> None:
        raise NotSupportedError("no look")

    monkeypatch.setattr(queued, "finds_sent", cannot)
    unclear_once(box, goes_out=False)
    job = box.queue()
    box.round()
    ended = box.job(job.id)
    assert (ended.state, ended.last_error) == ("unknown", "provider_unavailable")
    assert box.drafts() == [job.draft_id]
    assert ("unknown", "provider_unavailable") in box.outcomes()
    box.clock.tick(hours=1)
    box.round()
    assert box.sent() == []


def test_a_job_sending_when_the_service_stopped_is_looked_into(
    box: Outbox,
) -> None:
    job = box.queue()
    jobs = box.services.mailbox.outgoing.outbox.jobs
    jobs.update(job.model_copy(update={"state": "sending"}), was="queued")
    asyncio.run(box.runner.recover())
    waiting = box.job(job.id)
    assert (waiting.state, waiting.last_error) == ("queued", "interrupted")
    box.round()
    assert box.sent() == []
    box.clock.tick(minutes=15)
    box.round()
    assert box.job(job.id).state == "sent" and len(box.sent()) == 1
