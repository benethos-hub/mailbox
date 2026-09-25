"""The change log store, the same tests for both implementations."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import (
    Account,
    Change,
    ChangeType,
    ProviderType,
)
from benethos_mailbox_service.data.storage import (
    ChangeLogRepository,
    Database,
    InMemoryChangeLogRepository,
    SqliteAccountRepository,
    SqliteChangeLogRepository,
)

T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def log(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[ChangeLogRepository]:
    if request.param == "memory":
        yield InMemoryChangeLogRepository()
        return
    db = Database(tmp_path / "changes.db")
    accounts = SqliteAccountRepository(db)
    for account_id in ("acc_1", "acc_2"):
        accounts.add(
            Account(id=account_id, provider=ProviderType.IMAP, email="a@example.com")
        )
    yield SqliteChangeLogRepository(db)
    db.close()


def change(
    n: int,
    account_id: str = "acc_1",
    type: ChangeType = "message.created",
    minutes: int = 0,
) -> Change:
    return Change(
        type=type,
        id=f"msg_{n}",
        account_id=account_id,
        at=T0 + timedelta(minutes=minutes),
    )


def test_an_empty_log(log: ChangeLogRepository) -> None:
    assert log.last() == 0
    assert log.horizon() == 0
    assert log.after(["acc_1"], 0, limit=10) == []


def test_changes_are_numbered_in_order(log: ChangeLogRepository) -> None:
    log.append([change(1), change(2, type="message.updated")])
    log.append([change(3, "acc_2", "message.deleted")])
    found = log.after(["acc_1", "acc_2"], 0, limit=10)
    assert [e.seq for e in found] == [1, 2, 3]
    assert [e.change for e in found] == [
        change(1),
        change(2, type="message.updated"),
        change(3, "acc_2", "message.deleted"),
    ]
    assert log.last() == 3


def test_after_filters_by_number_account_and_limit(log: ChangeLogRepository) -> None:
    log.append([change(1), change(2, "acc_2"), change(3), change(4)])
    assert [e.change.id for e in log.after(["acc_1"], 1, limit=10)] == [
        "msg_3",
        "msg_4",
    ]
    assert [e.change.id for e in log.after(["acc_1", "acc_2"], 0, limit=2)] == [
        "msg_1",
        "msg_2",
    ]
    assert log.after([], 0, limit=10) == []


def test_purge_removes_old_changes_and_moves_the_horizon(
    log: ChangeLogRepository,
) -> None:
    log.append([change(1, minutes=0), change(2, minutes=5), change(3, minutes=10)])
    log.purge(T0 + timedelta(minutes=6))
    assert [e.seq for e in log.after(["acc_1"], 0, limit=10)] == [3]
    assert log.horizon() == 2
    # Numbers never come back.
    assert log.last() == 3
    log.append([change(4, minutes=20)])
    assert log.after(["acc_1"], 3, limit=10)[0].seq == 4


def test_the_horizon_never_goes_back(log: ChangeLogRepository) -> None:
    log.append([change(1, minutes=0), change(2, minutes=5)])
    log.purge(T0 + timedelta(minutes=6))
    log.purge(T0 + timedelta(minutes=1))
    assert log.horizon() == 2


def test_purging_nothing_keeps_the_horizon(log: ChangeLogRepository) -> None:
    log.append([change(1, minutes=10)])
    log.purge(T0)
    assert log.horizon() == 0


def test_the_last_number_survives_a_purge_of_everything(
    log: ChangeLogRepository,
) -> None:
    log.append([change(1), change(2)])
    log.purge(T0 + timedelta(days=1))
    assert log.after(["acc_1"], 0, limit=10) == []
    assert log.last() == 2
    assert log.horizon() == 2


def test_forget_account(log: ChangeLogRepository) -> None:
    log.append([change(1), change(2, "acc_2")])
    log.forget_account("acc_1")
    assert log.after(["acc_1", "acc_2"], 0, limit=10)[0].change.id == "msg_2"


def test_sqlite_keeps_the_log_across_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "reopen.db"
    db = Database(path)
    SqliteAccountRepository(db).add(
        Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
    )
    SqliteChangeLogRepository(db).append([change(1), change(2, minutes=10)])
    SqliteChangeLogRepository(db).purge(T0 + timedelta(minutes=1))
    db.close()
    db = Database(path)
    log = SqliteChangeLogRepository(db)
    assert log.last() == 2
    assert log.horizon() == 1
    assert [e.seq for e in log.after(["acc_1"], 0, limit=10)] == [2]
    db.close()


def test_sqlite_deleting_the_account_drops_its_changes(tmp_path: Path) -> None:
    db = Database(tmp_path / "cascade.db")
    accounts = SqliteAccountRepository(db)
    accounts.add(Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com"))
    log = SqliteChangeLogRepository(db)
    log.append([change(1)])
    accounts.delete("acc_1")
    assert log.after(["acc_1"], 0, limit=10) == []
    db.close()
