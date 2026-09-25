"""The id mapping store, the same tests for both implementations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import Account, ProviderType
from benethos_mailbox_service.data.storage import (
    Database,
    IndexChanges,
    IndexEntry,
    InMemoryMessageIndexRepository,
    MessageIndexRepository,
    SqliteAccountRepository,
    SqliteMessageIndexRepository,
)

ACC = "acc_1"


@pytest.fixture(params=["memory", "sqlite"])
def index(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[MessageIndexRepository]:
    if request.param == "memory":
        yield InMemoryMessageIndexRepository()
        return
    db = Database(tmp_path / "index.db")
    accounts = SqliteAccountRepository(db)
    for account_id in (ACC, "acc_2"):
        accounts.add(
            Account(id=account_id, provider=ProviderType.IMAP, email="a@example.com")
        )
    yield SqliteMessageIndexRepository(db)
    db.close()


def entry(n: int, folder: str = "f_inbox", header: str | None = None) -> IndexEntry:
    return IndexEntry(id=f"msg_{n}", native_id=f"n{n}", folder_id=folder, header=header)


def test_add_and_find(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1), entry(2, "f_sent", "<2@x>")])
    assert index.get(ACC, "msg_2") == entry(2, "f_sent", "<2@x>")
    assert index.get(ACC, "msg_9") is None
    assert index.get("acc_2", "msg_1") is None
    assert index.by_native(ACC, ["n1", "n7"]) == {"n1": entry(1)}
    assert index.in_folders(ACC, ["f_sent"]) == [entry(2, "f_sent", "<2@x>")]


def test_a_known_native_id_keeps_its_entry(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1)])
    index.add(ACC, [IndexEntry(id="msg_other", native_id="n1", folder_id="f_inbox")])
    assert index.by_native(ACC, ["n1"])["n1"].id == "msg_1"
    assert index.get(ACC, "msg_other") is None


def test_a_known_id_keeps_its_entry(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1)])
    index.add(ACC, [IndexEntry(id="msg_1", native_id="n5", folder_id="f_b")])
    assert index.get(ACC, "msg_1") == entry(1)
    assert index.by_native(ACC, ["n5"]) == {}


def test_relocating_an_unknown_id_changes_nothing(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(1)])
    index.relocate(ACC, IndexEntry(id="msg_9", native_id="n1", folder_id="f_b"))
    assert index.get(ACC, "msg_9") is None
    assert index.by_native(ACC, ["n1"])["n1"].id == "msg_1"


def test_apply_one_pass(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1), entry(2), entry(3)])
    moved = IndexEntry(
        id="msg_2", native_id="n20", folder_id="f_archive", header="<2@x>"
    )
    index.apply(
        ACC,
        IndexChanges(
            added=[entry(4, "f_archive")],
            updated=[moved],
            removed=["msg_3"],
            states={"f_inbox": "1.5.1", "f_archive": "1.3.2"},
        ),
    )
    assert index.get(ACC, "msg_3") is None
    assert index.get(ACC, "msg_2") == moved
    assert sorted(e.id for e in index.in_folders(ACC, ["f_archive"])) == [
        "msg_2",
        "msg_4",
    ]
    assert index.folder_states(ACC) == {"f_inbox": "1.5.1", "f_archive": "1.3.2"}

    index.apply(ACC, IndexChanges(states={"f_inbox": "1.6.1"}))
    assert index.folder_states(ACC) == {"f_inbox": "1.6.1"}


def test_an_update_takes_its_native_id_from_another_entry(
    index: MessageIndexRepository,
) -> None:
    # A listing gave the moved message a fresh entry before the sync saw the
    # move. The older id wins.
    index.add(
        ACC, [entry(1), IndexEntry(id="msg_new", native_id="n9", folder_id="f_b")]
    )
    index.apply(
        ACC,
        IndexChanges(updated=[IndexEntry(id="msg_1", native_id="n9", folder_id="f_b")]),
    )
    assert index.by_native(ACC, ["n9"])["n9"].id == "msg_1"
    assert index.get(ACC, "msg_new") is None


def test_many_native_ids_at_once(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(n) for n in range(1200)])
    assert len(index.by_native(ACC, [f"n{n}" for n in range(1200)])) == 1200
    assert len(index.in_folders(ACC, ["f_inbox"])) == 1200


def test_forget_account(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1)])
    index.add("acc_2", [entry(1)])
    index.apply(ACC, IndexChanges(states={"f_inbox": "s"}))
    index.forget_account(ACC)
    assert index.get(ACC, "msg_1") is None
    assert index.folder_states(ACC) == {}
    assert index.get("acc_2", "msg_1") == entry(1)


def test_deleting_an_account_drops_its_entries(tmp_path: Path) -> None:
    db = Database(tmp_path / "cascade.db")
    accounts = SqliteAccountRepository(db)
    accounts.add(Account(id=ACC, provider=ProviderType.IMAP, email="a@example.com"))
    index = SqliteMessageIndexRepository(db)
    index.add(ACC, [entry(1)])
    index.apply(ACC, IndexChanges(states={"f_inbox": "s"}))
    accounts.delete(ACC)
    assert index.get(ACC, "msg_1") is None
    assert index.folder_states(ACC) == {}
    db.close()
