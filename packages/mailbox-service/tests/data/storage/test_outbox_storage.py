"""The repository of the outbox: one contract, the same tests for the
in-memory and the SQLite implementation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import (
    Account,
    Before,
    OutboxJob,
    ProviderType,
)
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryOutboxRepository,
    OutboxRepository,
    SqliteAccountRepository,
    SqliteOutboxRepository,
)
from benethos_mailbox_service.errors import NotFoundError

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def job(name: str, **fields: object) -> OutboxJob:
    values: dict[str, object] = {
        "id": f"obx_{name}",
        "account_id": "acc_1",
        "user_id": "usr_1",
        "credential_id": "tok_1",
        "operation": "send_message",
        "draft_id": f"msg_{name}",
        "digest": "0" * 64,
        "message_id_header": f"<{name}@example.org>",
        "recipients": ["b@example.org"],
        "state": "queued",
        "due_at": NOW,
        "expires_at": NOW + timedelta(hours=48),
        "created_at": NOW,
    }
    values.update(fields)
    return OutboxJob.model_validate(values)


@pytest.fixture(params=["memory", "sqlite"])
def outbox(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[OutboxRepository]:
    if request.param == "memory":
        yield InMemoryOutboxRepository()
        return
    db = Database(tmp_path / "outbox.db")
    accounts = SqliteAccountRepository(db)
    for account_id in ("acc_1", "acc_2"):
        accounts.add(
            Account(id=account_id, provider=ProviderType.IMAP, email="a@example.org")
        )
    yield SqliteOutboxRepository(db)
    db.close()


def test_a_job_is_kept_as_it_came(outbox: OutboxRepository) -> None:
    queued = job(
        "a",
        send_at=NOW + timedelta(hours=1),
        unclear_since=NOW,
        last_error="provider_unavailable",
        attempts=2,
    )
    outbox.add(queued)
    assert outbox.get("obx_a") == queued


def test_an_unknown_job_is_not_found(outbox: OutboxRepository) -> None:
    with pytest.raises(NotFoundError):
        outbox.get("obx_none")


def test_an_update_needs_the_state_it_expects(outbox: OutboxRepository) -> None:
    outbox.add(job("a"))
    sending = job("a", state="sending", attempts=1)
    assert outbox.update(sending, was="queued")
    # A second run that also saw it queued does not take it.
    assert not outbox.update(job("a", state="sending", attempts=2), was="queued")
    assert outbox.get("obx_a") == sending


def test_an_update_of_an_unknown_job_stores_nothing(outbox: OutboxRepository) -> None:
    assert not outbox.update(job("a", state="sending"), was="queued")
    with pytest.raises(NotFoundError):
        outbox.get("obx_a")


def test_the_open_jobs_come_earliest_due_first(outbox: OutboxRepository) -> None:
    outbox.add(job("late", due_at=NOW + timedelta(minutes=5)))
    outbox.add(job("early", due_at=NOW - timedelta(minutes=5)))
    outbox.add(job("copying", state="copying", due_at=NOW))
    outbox.add(job("done", state="sent", finished_at=NOW))
    outbox.add(job("unclear", state="unknown", finished_at=NOW))
    outbox.add(job("aa_queued_later", created_at=NOW + timedelta(seconds=1)))
    assert [j.id for j in outbox.open()] == [
        "obx_early",
        "obx_copying",
        "obx_aa_queued_later",
        "obx_late",
    ]


def test_a_list_is_newest_first_and_narrowed(outbox: OutboxRepository) -> None:
    for minutes, name in ((0, "a"), (1, "b"), (2, "c")):
        outbox.add(job(name, created_at=NOW + timedelta(minutes=minutes)))
    outbox.add(job("other_user", user_id="usr_2"))
    outbox.add(job("other_account", account_id="acc_2"))
    outbox.add(job("failed", state="failed", finished_at=NOW))

    newest = outbox.list("acc_1", limit=2, before=None, user_id="usr_1")
    assert [j.id for j in newest] == ["obx_c", "obx_b"]
    last = newest[-1]
    rest = outbox.list(
        "acc_1", limit=10, before=Before(last.created_at, last.id), user_id="usr_1"
    )
    assert [j.id for j in rest] == ["obx_failed", "obx_a"]
    assert [
        j.id for j in outbox.list("acc_1", limit=10, before=None, state="failed")
    ] == ["obx_failed"]
    assert [j.id for j in outbox.list("acc_2", limit=10, before=None)] == [
        "obx_other_account"
    ]


def test_the_purge_removes_finished_jobs_only(outbox: OutboxRepository) -> None:
    old = NOW - timedelta(days=100)
    outbox.add(job("old_sent", state="sent", finished_at=old))
    outbox.add(job("new_sent", state="sent", finished_at=NOW))
    outbox.add(job("old_open", created_at=old, due_at=old))
    assert outbox.purge(NOW - timedelta(days=90)) == 1
    assert {j.id for j in outbox.list("acc_1", limit=10, before=None)} == {
        "obx_new_sent",
        "obx_old_open",
    }
