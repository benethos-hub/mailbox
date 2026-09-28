"""The activities of the running service: sync, sending, webhooks,
discovery, the log page and the limits (docs/LOGGING.md 5.5 to 5.9)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import anyio
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Grant,
    OutgoingMessage,
    Recipient,
)
from benethos_mailbox_service.data.storage import InMemoryChangeLogRepository
from benethos_mailbox_service.domain import worker as worker_module
from benethos_mailbox_service.domain.changes import ChangeFeed, MessagesCreated
from benethos_mailbox_service.domain.delivery import Retries
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    RateLimitedError,
    RecipientNotAllowedError,
    SendLimitError,
    UnauthorizedError,
)
from benethos_mailbox_service.main import Services, build_services, create_app
from benethos_mailbox_service.web import limits

from .conftest import ADMIN, CHEAP
from .imap_fake import FakeMailBox
from .test_delivery import (  # noqa: F401
    Clock,
    Receiver,
    clock,
    hook,
    mark_read,
    receiver,
)
from .test_discovery import ISPDB, FakeSource, service
from .test_sync import imap_account_id, imap_services, server  # noqa: F401
from .test_worker import worker

WHO = "test admin (usr_test_admin)"

pytestmark = pytest.mark.usefixtures("master_key")
TO = OutgoingMessage(to=[Recipient(email="you@example.com")], text="Hi")


def lines(caplog: pytest.LogCaptureFixture, *, level: int = logging.DEBUG) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if ".activity." in r.name
        and not r.name.endswith(".key_from_env")
        and r.levelno >= level
    ]


# --- sync ---------------------------------------------------------------------------


async def test_a_watcher_names_the_account_each_pass_and_each_renewal(
    imap_services: Services,  # noqa: F811
    imap_account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(worker_module, "IDLE_RENEW", 0.05)
    with caplog.at_level(logging.DEBUG):
        await imap_services.sync.sync_account(imap_account_id)
        with anyio.move_on_after(0.2):
            await worker(imap_services).watch(imap_account_id)
    named = f"me@example.com ({imap_account_id})"
    found = lines(caplog)
    assert found[0].startswith(f"the service synced {named}: ")
    assert found[0].endswith(" +0 -0 ~0")
    assert f"the worker watches {named} for changes the server pushes" in found
    assert f"the worker renewed IDLE on {named}" in found


async def test_the_worker_names_how_it_runs(
    imap_services: Services,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Stop(Exception):
        pass

    async def stop(seconds: float) -> None:
        raise Stop

    background = worker(imap_services, push=False)
    background._sleep = stop
    with caplog.at_level(logging.INFO):
        try:
            await background.run()
        except* Stop:
            pass
    assert "the worker started: it syncs every 300s without push" in lines(caplog)


def test_a_purge_of_the_change_log_names_how_many(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = [datetime(2026, 9, 28, 12, 0, tzinfo=UTC)]
    feed = ChangeFeed(InMemoryChangeLogRepository(), days=1, clock=lambda: now[0])
    feed.record(MessagesCreated("acc_1", ["m1", "m2"]))
    now[0] += timedelta(days=2)
    with caplog.at_level(logging.INFO):
        feed.purge()
        feed.purge()
    assert lines(caplog) == [
        "the service purged 2 changes older than 2026-09-29T12:00:00+00:00 from "
        "the change log"
    ]


# --- sending ------------------------------------------------------------------------


async def test_a_send_names_the_count_of_recipients_never_their_addresses(
    services: Services, account_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        first = await services.mailbox.outgoing.send_message(
            ADMIN, account_id, TO, idempotency_key="k1"
        )
        await services.mailbox.outgoing.send_message(
            ADMIN, account_id, TO, idempotency_key="k1"
        )
    sent = first.sent_copy_id or first.message_id_header
    assert lines(caplog) == [
        f"{WHO} sent a message from me@example.com ({account_id}) to 1 recipient: "
        f"{sent}",
        f"the service answered send_message on {account_id} with the result of its "
        "Idempotency-Key",
    ]
    assert "you@example.com" not in caplog.text


async def test_a_refused_send_names_the_code_not_the_recipient(
    services: Services, account_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    only = Access(
        "usr_1",
        "Anna",
        [Grant(accounts=[account_id], allow=["send"], recipients=["*@example.org"])],
    )
    with pytest.raises(RecipientNotAllowedError):
        await services.mailbox.outgoing.send_message(only, account_id, TO)
    assert lines(caplog) == [
        f"Anna (usr_1) was refused to send from {account_id}: recipient_not_allowed"
    ]
    assert "you@example.com" not in caplog.text


async def test_the_send_limit_is_logged_with_its_counts(
    services: Services, account_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    once = Access(
        "usr_1",
        "Anna",
        [Grant(accounts=[account_id], allow=["send"], max_sends_per_day=1)],
    )
    await services.mailbox.outgoing.send_message(once, account_id, TO)
    with pytest.raises(SendLimitError):
        await services.mailbox.outgoing.send_message(once, account_id, TO)
    [line] = lines(caplog, level=logging.WARNING)
    assert line.startswith(
        f"Anna (usr_1) reached the send limit on {account_id}: 1 mails sent from "
        "this account in 24 hours, the grants allow 1, the next in "
    )


# --- webhooks -----------------------------------------------------------------------


async def test_a_webhook_from_creation_to_removal(
    client: TestClient,
    services: Services,
    account_id: str,
    receiver: Receiver,  # noqa: F811
    clock: Clock,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        created = hook(client, url="https://hooks.example.com/mail?key=abc")
        mark_read(client, account_id, "m0")
        receiver.status = 503
        await services.deliveries.deliver_due()
        clock.now += timedelta(seconds=31)
        receiver.status = 200
        await services.deliveries.deliver_due()
        client.delete(f"/v1/webhooks/{created['id']}")
    webhook = created["id"]
    found = lines(caplog)
    assert found[0].endswith(
        f"created webhook {webhook} to hooks.example.com for message.created, "
        "message.updated, message.deleted, message.sent, account.needs_reauth of "
        "every account from testclient"
    )
    assert found[1:3] == [
        f"the dispatcher could not post for webhook {webhook}, attempt 1 of 8: "
        "the receiver answered 503",
        f"the dispatcher posted for webhook {webhook} again",
    ]
    assert found[3].endswith(
        f"removed webhook {webhook} to hooks.example.com from testclient"
    )
    assert "key=abc" not in caplog.text


async def test_a_webhook_that_gives_up(
    client: TestClient,
    services: Services,
    account_id: str,
    receiver: Receiver,  # noqa: F811
    clock: Clock,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services.deliveries, "_retries", Retries(attempts=1))
    created = hook(client)
    mark_read(client, account_id, "m0")
    receiver.status = 500
    await services.deliveries.deliver_due()
    assert lines(caplog, level=logging.WARNING) == [
        f"the dispatcher gave up on 1 change for webhook {created['id']} after 1 "
        "attempts: the receiver answered 500"
    ]


# --- discovery, the log page ----------------------------------------------------------


async def test_discovery_names_the_domain_and_its_limit_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    s = service(FakeSource(ISPDB), per_user=1)
    with caplog.at_level(logging.DEBUG):
        await s.discover(ADMIN, "anna@firma.example")
        for _ in range(2):
            with pytest.raises(RateLimitedError):
                await s.discover(ADMIN, "anna@firma.example")
    assert lines(caplog) == [
        f"{WHO} looked up the servers of firma.example: 0 candidates from 1 source",
        f"{WHO} reached the discovery limit of 1 in a minute",
    ]
    assert "anna" not in caplog.text


def test_reading_the_log_is_logged_once_per_visit(
    services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        services.log.lines(ADMIN)
        services.log.lines(ADMIN, cursor="5")
    assert lines(caplog) == [f"{WHO} read the service log"]


# --- limits -------------------------------------------------------------------------


class Now:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def test_a_lockout_and_the_name_brake_are_logged_when_they_engage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = Now()
    services = build_services(
        Settings(storage="memory"), password_hasher=CHEAP, clock=now
    )
    anna = services.users.create_user(ADMIN, "Anna", [], [], ui_sign_in=True)
    await services.auth.passwords.set(
        anna.id, "Anna", "a long password", must_change=False
    )
    caplog.set_level(logging.INFO)
    for _ in range(12):
        try:
            await services.auth.sign_in("Anna", "wrong", source="10.0.0.9")
        except (UnauthorizedError, RateLimitedError):
            pass
    now.now += timedelta(minutes=16)
    await services.auth.sign_in("Anna", "a long password", source="10.0.0.9")
    found = [
        line for line in lines(caplog) if "failed to sign in to the UI" not in line
    ]
    assert found == [
        "someone failed to sign in too often from 10.0.0.9: locked out for 15 minutes",
        f"someone failed to sign in as Anna ({anna.id}) too often from 10.0.0.9: the "
        "name waits 60 seconds",
        "someone may try to sign in again from 10.0.0.9: the lockout ended",
        f"Anna ({anna.id}) signed in to the UI from 10.0.0.9",
    ]


def test_a_body_too_large_is_logged_by_the_web_layer(
    settings: Settings,
    services: Services,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(limits, "MAX_BODY", 1024 * 1024)
    client = TestClient(create_app(settings, services))
    answer = client.post("/v1/webhooks", content=b"x" * (1024 * 1024 + 1))
    assert answer.status_code == 413
    assert lines(caplog) == [
        "someone sent a request to /v1/webhooks larger than 1 MB from testclient: "
        "refused"
    ]
