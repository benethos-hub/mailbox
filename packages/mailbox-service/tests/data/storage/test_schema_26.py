"""Schema 26: every order in a column, the active key and the last
number of the change feed in ``meta``. A database of schema 25, made by
the migrations, keeps what it held."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.storage import (
    Database,
    SqliteChangeLogRepository,
    SqliteMessageIndexRepository,
    SqliteRoleRepository,
    SqliteUserRepository,
    ThreadChain,
)
from benethos_mailbox_service.data.storage.sqlite import SqliteKeyRepository
from benethos_mailbox_service.data.storage.sqlite.users import ascii_lower
from benethos_mailbox_service.errors import ConflictError

from .old_schema import at_schema

KEYS_IN_META = ("active_key", "changes_last")


def test_the_index_keeps_its_order_through_schema_26(tmp_path: Path) -> None:
    """The order came from the hidden rowid and is a column since: ids
    that do not sort, a deleted entry between, a thread born later
    whose id sorts first."""
    path = tmp_path / "old.db"
    raw = at_schema(path, 25)
    raw.execute(
        "INSERT INTO accounts (id, provider, email, status, settings)"
        " VALUES ('acc_1', 'imap', 'a@example.org', 'active', '{}')"
    )
    for message, thread in (
        ("msg_c", "thr_z"),
        ("msg_a", None),
        ("msg_b", "thr_a"),
        ("msg_e", None),
        ("msg_d", "thr_z"),
    ):
        raw.execute(
            "INSERT INTO message_index (account_id, id, native_id, folder_id,"
            " thread_id) VALUES ('acc_1', ?, ?, 'f_inbox', ?)",
            (message, f"n_{message}", thread),
        )
    raw.execute("DELETE FROM message_index WHERE id = 'msg_a'")
    for header, thread in (("<z@x>", "thr_z"), ("<a@x>", "thr_a")):
        raw.execute(
            "INSERT INTO thread_links (account_id, header, thread_id)"
            " VALUES ('acc_1', ?, ?)",
            (header, thread),
        )
    raw.close()
    db = Database(path)
    rows = db.query("SELECT seq, id FROM message_index ORDER BY seq")
    assert [tuple(r) for r in rows] == [
        (1, "msg_c"),
        (3, "msg_b"),
        (4, "msg_e"),
        (5, "msg_d"),
    ]
    index = SqliteMessageIndexRepository(db)
    ids = [e.id for e in index.in_folders("acc_1", ["f_inbox"])]
    assert ids == ["msg_c", "msg_b", "msg_e", "msg_d"]
    assert [e.id for e in index.in_thread("acc_1", "thr_z")] == ["msg_c", "msg_d"]
    assert [e.id for e in index.unthreaded("acc_1", 5)] == ["msg_e"]
    merged = index.thread(
        "acc_1",
        [ThreadChain(message_id="msg_e", headers=("<a@x>", "<z@x>"))],
        lambda: "thr_new",
    )
    assert merged == {"msg_b": "thr_z"}
    db.close()


def test_users_and_roles_keep_their_places_through_schema_26(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.db"
    raw = at_schema(path, 25)
    for name in ("b", "a", "c"):
        raw.execute("INSERT INTO users (id, name) VALUES (?, ?)", (f"usr_{name}", name))
        raw.execute("INSERT INTO roles (id, grants) VALUES (?, '[]')", (f"r_{name}",))
    raw.execute("DELETE FROM users WHERE id = 'usr_a'")
    raw.close()
    db = Database(path)
    rows = db.query("SELECT id, position FROM users ORDER BY position")
    assert [tuple(r) for r in rows] == [("usr_b", 1), ("usr_c", 3)]
    users = SqliteUserRepository(db)
    users.save(User(id="usr_d", name="d"))
    assert [u.id for u in users.list()] == ["usr_b", "usr_c", "usr_d"]
    roles = [r.id for r in SqliteRoleRepository(db).list()]
    assert roles == ["r_b", "r_a", "r_c"]
    db.close()


def test_the_active_key_and_the_last_change_move_to_meta(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    raw = at_schema(path, 25)
    raw.execute(
        "INSERT INTO accounts (id, provider, email, status, settings)"
        " VALUES ('acc_1', 'imap', 'a@example.org', 'active', '{}')"
    )
    for key in ("key_b", "key_a"):
        raw.execute(
            "INSERT INTO keys (key_id, nonce, ciphertext) VALUES (?, x'00', x'00')",
            (key,),
        )
    for n in range(3):
        raw.execute(
            "INSERT INTO changes (account_id, message_id, type, at)"
            " VALUES ('acc_1', ?, 'message.created', '2026-11-25T00:00:00Z')",
            (f"msg_{n}",),
        )
    raw.execute("DELETE FROM changes WHERE seq = 3")
    raw.close()
    db = Database(path)
    meta = dict(
        db.query("SELECT key, value FROM meta WHERE key IN (?, ?)", KEYS_IN_META)
    )
    assert meta == {"active_key": "key_a", "changes_last": "3"}
    key = SqliteKeyRepository(db).active()
    assert key is not None
    assert key.key_id == "key_a"
    assert SqliteChangeLogRepository(db).last() == 3
    db.close()


def test_a_new_database_has_no_key_and_no_change(tmp_path: Path) -> None:
    db = Database(tmp_path / "new.db")
    assert SqliteKeyRepository(db).active() is None
    assert SqliteChangeLogRepository(db).last() == 0
    db.close()


@pytest.mark.parametrize(
    "name", ["Admin", "ADMIN", "Ärger", "ärger", "İstanbul", "ıi", "Straße", "ΣΑΣ"]
)
def test_a_name_is_folded_as_sqlite_folds_it(name: str) -> None:
    with closing(sqlite3.connect(":memory:")) as raw:
        assert (
            ascii_lower(name) == raw.execute("SELECT lower(?)", (name,)).fetchone()[0]
        )


def test_names_are_unique_by_their_ascii_letters(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    raw = at_schema(path, 25)
    raw.execute("INSERT INTO users (id, name) VALUES ('usr_1', 'Anna')")
    raw.close()
    db = Database(path)
    rows = db.query("SELECT name, name_lower FROM users")
    assert [tuple(r) for r in rows] == [("Anna", "anna")]
    users = SqliteUserRepository(db)
    with pytest.raises(ConflictError):
        users.save(User(id="usr_2", name="ANNA"))
    # Beyond ASCII the index lets both in. The domain refuses the second.
    users.save(User(id="usr_3", name="Ärger"))
    users.save(User(id="usr_4", name="ärger"))
    users.save(User(id="usr_1", name="Anna Maria"))
    users.save(User(id="usr_5", name="anna"))
    assert [u.name for u in users.list()] == ["Anna Maria", "Ärger", "ärger", "anna"]
    db.close()
