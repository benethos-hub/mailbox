"""Sending: no wider send handed out, the send control, its log in SQLite
and its retention (CONCEPT 7.5, 7.7)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.data.models import (
    Before,
    Grant,
    SendFilter,
    SendRecord,
    SentMessage,
)
from benethos_mailbox_service.data.storage import (
    Database,
    InMemorySendLogRepository,
    SqliteSendLogRepository,
)
from benethos_mailbox_service.domain.mailbox.sending import SendControl
from benethos_mailbox_service.domain.rights.access import (
    Access,
)
from benethos_mailbox_service.errors import (
    ProviderError,
    RecipientNotAllowedError,
    SendLimitError,
    StorageError,
)

# --- no escalation --------------------------------------------------------------------


def manager(*grants: Grant) -> Access:
    return Access(
        "usr_m", "manager", [Grant(accounts=[], allow=["users.manage"]), *grants]
    )


def test_a_limited_sender_hands_out_no_wider_send() -> None:
    limited = manager(
        Grant(
            accounts=["acc_1"],
            allow=["send"],
            recipients=["*@a.org"],
            max_sends_per_day=5,
        )
    )
    assert limited.covers(
        [
            Grant(
                accounts=["acc_1"],
                allow=["send"],
                recipients=["bob@a.org"],
                max_sends_per_day=3,
            )
        ]
    )
    assert not limited.covers([Grant(accounts=["acc_1"], allow=["send"])])
    assert not limited.covers(
        [
            Grant(
                accounts=["acc_1"],
                allow=["send"],
                recipients=["*@b.org"],
                max_sends_per_day=1,
            )
        ]
    )
    assert not limited.covers(
        [Grant(accounts=["acc_1"], allow=["send"], recipients=["*@a.org"])]
    )
    assert not limited.covers(
        [
            Grant(
                accounts=["acc_1"],
                allow=["send"],
                recipients=["*@a.org"],
                max_sends_per_day=6,
            )
        ]
    )


def test_an_unlimited_sender_hands_out_any_send() -> None:
    free = manager(Grant(accounts=["*"], allow=["send"]))
    assert free.covers([Grant(accounts=["*"], allow=["send"])])
    assert free.covers([Grant(accounts=["*"], allow=["send"], recipients=["*@a.org"])])


def test_limits_on_every_account() -> None:
    limited = manager(Grant(accounts=["*"], allow=["send"], recipients=["*@a.org"]))
    assert limited.covers(
        [Grant(accounts=["*"], allow=["send"], recipients=["*@a.org"])]
    )
    assert not limited.covers([Grant(accounts=["*"], allow=["send"])])


# --- the control itself ---------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def sent() -> SentMessage:
    return SentMessage()


def test_the_limit_frees_up_after_24_hours() -> None:
    clock = Clock()
    control = SendControl(InMemorySendLogRepository(), clock)
    access = Access(
        "usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"], max_sends_per_day=1)]
    )

    def send() -> SentMessage:
        return asyncio.run(
            control.send(access, "send_message", "acc_1", ["a@x.org"], sent, "<m>")
        )

    send()
    clock.now += timedelta(hours=23)
    with pytest.raises(SendLimitError) as stopped:
        send()
    assert stopped.value.retry_after == 3600
    clock.now += timedelta(hours=1)
    send()


def test_a_failed_send_is_recorded_and_not_counted() -> None:
    store = InMemorySendLogRepository()
    control = SendControl(store)
    access = Access(
        "usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"], max_sends_per_day=1)]
    )

    async def failing() -> SentMessage:
        raise ProviderError("the server hung up")

    with pytest.raises(ProviderError):
        asyncio.run(
            control.send(access, "send_message", "acc_1", ["a@x.org"], failing, "<m>")
        )
    [record] = store.list("acc_1", limit=10, before=None)
    assert (record.outcome, record.error) == ("failed", "provider_error")
    asyncio.run(control.send(access, "send_message", "acc_1", ["a@x.org"], sent, "<m>"))


def test_a_send_the_audit_cannot_record_is_still_sent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Full(InMemorySendLogRepository):
        def add(self, record: SendRecord) -> None:
            raise StorageError("the disk is full")

    access = Access("usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"])])
    result = asyncio.run(
        SendControl(Full()).send(
            access, "send_message", "acc_1", ["a@x.org"], sent, "<m>"
        )
    )
    assert result == asyncio.run(sent())
    assert (
        "u (usr_1) sent a message from acc_1, but it is not in the audit" in caplog.text
    )


def test_no_grant_at_all_allows_nothing() -> None:
    control = SendControl(InMemorySendLogRepository())
    with pytest.raises(RecipientNotAllowedError):
        asyncio.run(
            control.send(
                Access("u", "u", []), "send_message", "a", ["x@y.z"], sent, "<m>"
            )
        )


# --- SQLite ---------------------------------------------------------------------------


def test_sqlite_send_log(tmp_path: object) -> None:
    db = Database()
    try:
        clock = Clock()
        store = SqliteSendLogRepository(db)
        control = SendControl(store, clock)
        access = Access(
            "usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"])], "tok_1"
        )
        for n in range(3):
            clock.now += timedelta(minutes=1)
            asyncio.run(
                control.send(
                    access, "send_draft", "acc_1", [f"{n}@x.org"], sent, f"<{n}>"
                )
            )
        records = store.list("acc_1", limit=2, before=None)
        assert [r.recipients for r in records] == [["2@x.org"], ["1@x.org"]]
        older = store.list(
            "acc_1", limit=5, before=Before(records[-1].created_at, records[-1].id)
        )
        assert [r.recipients for r in older] == [["0@x.org"]]
        assert records[0].credential_id == "tok_1"
        assert records[0].operation == "send_draft"
        since = clock.now - timedelta(minutes=1, seconds=30)
        assert len(store.sent_since("usr_1", "acc_1", since, outcome="sent")) == 2
        assert store.sent_since("usr_2", "acc_1", since, outcome="sent") == []
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_the_send_log_filters(kind: str) -> None:
    db = Database()
    store = (
        InMemorySendLogRepository() if kind == "memory" else SqliteSendLogRepository(db)
    )
    at = datetime(2026, 9, 27, 12, tzinfo=UTC)
    for n, (user, outcome, to) in enumerate(
        [
            ("usr_1", "sent", "Bob@Example.org"),
            ("usr_2", "denied", "eve@elsewhere.example"),
            ("usr_1", "sent", "carol@example.org"),
            ("usr_3", "sent", "jörg@example.org"),
        ]
    ):
        store.add(
            SendRecord(
                id=f"snd_{n}",
                created_at=at + timedelta(days=n),
                user_id=user,
                credential_id=None,
                account_id="acc_1",
                operation="send_message",
                recipients=[to],
                outcome=outcome,  # type: ignore[arg-type]
            )
        )

    def ids(**fields: object) -> list[str]:
        found = store.list(
            "acc_1", limit=10, before=None, matching=SendFilter(**fields)
        )
        return [r.id for r in found]

    assert store.account_ids() == ["acc_1"]
    assert ids(user_id="usr_1") == ["snd_2", "snd_0"]
    assert ids(outcome="denied") == ["snd_1"]
    assert ids(recipient="bob@") == ["snd_0"]
    assert ids(recipient='"') == []  # never the JSON around the addresses
    assert ids(recipient="JÖRG") == ["snd_3"]  # folded beyond ASCII too
    assert ids(after=at + timedelta(days=1)) == ["snd_3", "snd_2", "snd_1"]
    assert ids(before=at + timedelta(days=1)) == ["snd_0"]
    assert (
        len(
            store.list(
                "acc_1", limit=1, before=None, matching=SendFilter(user_id="usr_1")
            )
        )
        == 1
    )
    db.close()


# --- retention --------------------------------------------------------------------


def test_old_records_are_purged_once_an_hour(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    store = InMemorySendLogRepository()
    control = SendControl(store, clock, days=1)
    access = Access("usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"])])

    def send() -> int:
        asyncio.run(
            control.send(access, "send_message", "acc_1", ["a@x.org"], sent, "<m>")
        )
        return len(store.list("acc_1", limit=10, before=None))

    assert send() == 1
    clock.now += timedelta(minutes=50)
    assert send() == 2
    # A day and a bit later the first record is older than a day, and the
    # purge is due: it goes, and the log says so.
    clock.now += timedelta(hours=23, minutes=20)
    with caplog.at_level(logging.INFO):
        assert send() == 2
    assert "purged 1 record older than" in caplog.text
    # The second is older than a day now too, but the purge ran less than
    # an hour ago: it stays until the next one.
    clock.now += timedelta(minutes=45)
    assert send() == 3
    clock.now += timedelta(minutes=16)
    assert send() == 3


def test_zero_keeps_every_record() -> None:
    clock = Clock()
    store = InMemorySendLogRepository()
    control = SendControl(store, clock, days=0)
    access = Access("usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"])])
    for _ in range(3):
        asyncio.run(
            control.send(access, "send_message", "acc_1", ["a@x.org"], sent, "<m>")
        )
        clock.now += timedelta(days=400)
    assert len(store.list("acc_1", limit=10, before=None)) == 3


def test_the_days_come_from_the_settings() -> None:
    from benethos_mailbox_service.assembly import build_services
    from benethos_mailbox_service.config import Settings

    services = build_services(Settings(storage="memory", audit_days=30))
    assert services.mailbox.outgoing._sends.days == 30
