"""The tables of the database as stored, for the logical export: every
table in the order of its references, the rows read in chunks, written
back unchanged."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import ChangeRecord
from benethos_mailbox_service.data.storage import (
    Database,
    SqliteChangeLogRepository,
)
from benethos_mailbox_service.data.storage.sqlite import SCHEMA_VERSION, database
from benethos_mailbox_service.errors import StorageError

AT = "2026-11-25T12:00:00Z"


def _filled() -> Database:
    db = Database()
    db.execute(
        "INSERT INTO accounts (id, provider, email, status, settings, position)"
        " VALUES ('acc_1', 'imap', 'a@example.org', 'connected', '{}', 1)"
    )
    db.execute(
        "INSERT INTO keys (key_id, nonce, ciphertext) VALUES ('k1', ?, ?)",
        (b"\x00\xff\x10", bytes(range(256))),
    )
    db.execute(
        "INSERT INTO activity (id, at, activity, user_id, user_name, outcome,"
        " detail) VALUES ('act_1', ?, 'user.created', NULL, 'two\nlines', 'done',"
        " '{}')",
        (AT,),
    )
    return db


def test_every_table_is_named_after_those_it_refers_to() -> None:
    db = Database()
    tables = db.tables()
    names = [t.name for t in tables]
    stored = db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
        " AND name NOT LIKE 'sqlite_%'"
    )
    assert sorted(names) == sorted(r[0] for r in stored)
    assert "meta" in names
    for table in tables:
        refers = db.query(f"SELECT * FROM pragma_foreign_key_list('{table.name}')")
        for ref in refers:
            if ref["table"] != table.name:
                assert names.index(ref["table"]) < names.index(table.name)
    by_name = {t.name: t for t in tables}
    assert by_name["credentials"].key == ("account_id", "field")
    assert by_name["changes"].columns[0] == "seq"
    db.close()


def test_rows_come_back_as_they_went_in() -> None:
    source = _filled()
    target = Database()
    for table in source.tables():
        target.fill(table.name, table.columns, source.rows(table.name))
    for table in source.tables():
        assert list(target.rows(table.name)) == list(source.rows(table.name))
    [key] = target.rows("keys")
    assert key[1:3] == (b"\x00\xff\x10", bytes(range(256)))
    [act] = target.rows("activity")
    assert None in act
    assert "two\nlines" in act
    source.close()
    target.close()


def test_rows_are_read_in_chunks_in_the_order_of_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "ROWS_CHUNK", 3)
    db = _filled()
    for n in (5, 1, 4, 2, 3, 7, 6):
        db.execute(
            "INSERT INTO changes (seq, account_id, message_id, type, at)"
            " VALUES (?, 'acc_1', 'm', 'message.created', ?)",
            (n, AT),
        )
    assert [row[0] for row in db.rows("changes")] == [1, 2, 3, 4, 5, 6, 7]
    db.close()


def test_a_filled_feed_counts_on_from_its_last_number() -> None:
    source = _filled()
    feed = SqliteChangeLogRepository(source)
    record = ChangeRecord(
        type="message.created",
        id="msg_1",
        account_id="acc_1",
        at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    feed.append([record, record, record])
    source.execute("DELETE FROM changes WHERE seq > 1")
    target = Database()
    for table in source.tables():
        target.fill(table.name, table.columns, source.rows(table.name))
    SqliteChangeLogRepository(target).append([record])
    assert [r[0] for r in target.rows("changes")] == [1, 4]
    source.close()
    target.close()


def test_fill_refuses_what_does_not_fit() -> None:
    db = _filled()
    with pytest.raises(StorageError, match="not empty"):
        db.fill("keys", ["key_id", "nonce", "ciphertext"], [("k2", b"", b"")])
    with pytest.raises(StorageError, match="do not fit the table roles"):
        db.fill("roles", ["id", "nope"], [("r", 1)])
    with pytest.raises(StorageError, match="no table nope"):
        db.fill("nope", ["id"], [])
    with pytest.raises(StorageError, match="no table nope"):
        list(db.rows("nope"))
    db.close()


def test_a_new_database_is_made_at_an_older_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db", schema=20)
    assert db.schema_version() == 20
    assert "outbox" not in [t.name for t in db.tables()]
    db.close()
    with pytest.raises(StorageError, match="no way from schema 0 to 99"):
        Database(tmp_path / "new.db", schema=99)
    db = Database(tmp_path / "old.db")
    assert db.schema_version() == SCHEMA_VERSION
    db.close()
