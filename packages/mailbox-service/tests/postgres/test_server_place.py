"""A database on PostgreSQL through its place: the baseline in the schema
of a role without rights, the definitions as the server holds them, the
order of text, and the transactions of the one connection."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.models import (
    Account,
    ChangeRecord,
    ProviderType,
    User,
)
from benethos_mailbox_service.data.storage import (
    SCHEMA_VERSION,
    Database,
    ServerPlace,
    repositories_on,
)
from benethos_mailbox_service.data.storage.sql.schema import METADATA
from benethos_mailbox_service.errors import NotFoundError, StorageError

from ..postgres_helpers import (
    connect,
    database,
    in_transaction,
    role,
    schema,
    server,
)


def _definitions_differ(conn: sa.Connection) -> list[str]:
    """Where the tables of the server differ from ``schema.py``: columns,
    types, NOT NULL, foreign keys with ON DELETE, indexes."""
    inspector = sa.inspect(conn)
    found: list[str] = []
    for table in METADATA.sorted_tables:
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            held = columns.pop(column.name, None)
            if held is None:
                found.append(f"{table.name}.{column.name}: missing")
                continue
            wanted = column.type.compile(dialect=conn.dialect)
            if wanted.replace("BIGSERIAL", "BIGINT") != held["type"].compile(
                dialect=conn.dialect
            ):
                found.append(f"{table.name}.{column.name}: type")
            if not column.primary_key and bool(held["nullable"]) != bool(
                column.nullable
            ):
                found.append(f"{table.name}.{column.name}: NOT NULL")
        found += [f"{table.name}.{name}: only on the server" for name in columns]
        keys = {
            (tuple(fk.column_keys), fk.referred_table.name, fk.ondelete)
            for fk in table.foreign_key_constraints
        }
        held_keys = {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                fk["options"].get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table.name)
        }
        if keys != held_keys:
            found.append(f"{table.name}: foreign keys")
        indexes = {
            (i.name, bool(i.unique), tuple(c.name for c in i.columns))
            for i in table.indexes
        }
        held_indexes = {
            (i["name"], bool(i["unique"]), tuple(i["column_names"]))
            for i in inspector.get_indexes(table.name)
            if not i.get("duplicates_constraint")
        }
        if indexes != held_indexes:
            found.append(f"{table.name}: indexes")
    return found


def test_the_baseline_lands_in_the_schema_of_a_role_without_rights() -> None:
    with role() as server:
        db = Database(place=ServerPlace(server))
        try:
            assert db.schema_version() == SCHEMA_VERSION
            with db.connected() as conn:
                tables = sa.inspect(conn).get_table_names()
                differ = _definitions_differ(conn)
        finally:
            db.close()
        with connect() as admin:
            where = admin.execute(
                "SELECT DISTINCT table_schema FROM information_schema.tables"
                " WHERE table_name IN ('meta', 'alembic_version', 'accounts')",
            ).fetchall()
    assert len(tables) == len(METADATA.sorted_tables) + 1
    assert "alembic_version" in tables
    assert (server.role,) in where
    assert ("public",) not in where
    assert differ == []


def test_every_text_column_compares_byte_for_byte() -> None:
    """The order of text holds only with the collation C: a comparison of
    two times would not show the difference on either image."""
    with schema() as name:
        database(name).close()
        with connect() as admin:
            collations = admin.execute(
                "SELECT collation_name, count(*) FROM information_schema.columns"
                " WHERE table_schema = %s AND data_type = 'text' GROUP BY 1",
                (name,),
            ).fetchall()
    assert len(collations) == 1
    assert collations[0][0] == "C"
    assert collations[0][1] > 100


def test_a_schema_before_the_baseline_is_not_on_a_server() -> None:
    with schema() as name, pytest.raises(StorageError, match="begins at schema 26"):
        database(name, schema=25)


def _change(n: int) -> ChangeRecord:
    return ChangeRecord(
        type="message.created",
        id=f"msg_{n}",
        account_id="acc_1",
        at=datetime(2026, 11, 26, tzinfo=UTC),
    )


def _undone(db: Database, write: Callable[[], object]) -> None:
    """``write`` in a transaction, inside another one or not, that fails
    after it and is undone."""
    with pytest.raises(RuntimeError), db.transaction():
        write()
        raise RuntimeError


def test_two_writers_on_two_threads_go_one_after_the_other() -> None:
    with schema() as name:
        db = database(name)
        repositories_on(db).accounts.add(
            Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
        )
        feed = repositories_on(db).changes

        def write(start: int) -> None:
            for n in range(start, start + 25):
                feed.append([_change(n)])

        threads = [threading.Thread(target=write, args=(s,)) for s in (0, 100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            numbers = [c.seq for c in feed.after(["acc_1"], 0, limit=100)]
        finally:
            db.close()
    assert len(numbers) == 50
    assert len(set(numbers)) == 50


def test_a_savepoint_is_undone_alone() -> None:
    with schema() as name:
        db = database(name)
        users = repositories_on(db).users
        try:
            with db.transaction():
                users.save(User(id="usr_kept", name="kept"))
                _undone(db, lambda: users.save(User(id="usr_undone", name="undone")))
            assert users.get("usr_kept").name == "kept"
            with pytest.raises(NotFoundError):
                users.get("usr_undone")
        finally:
            db.close()


def test_a_read_leaves_no_transaction_open() -> None:
    with schema() as name:
        db = database(name)
        try:
            with pytest.raises(NotFoundError):
                repositories_on(db).users.get("usr_none")
            assert not in_transaction(db)
            repositories_on(db).users.list()
            assert not in_transaction(db)
            with db.transaction():
                repositories_on(db).users.save(User(id="usr_1", name="one"))
            assert not in_transaction(db)
        finally:
            db.close()


def test_a_change_undone_leaves_a_gap_the_feed_reads_past() -> None:
    """On PostgreSQL a number a rolled back insert took is gone: the feed
    goes on after the gap and hands out each change once."""
    with schema() as name:
        db = database(name)
        stores = repositories_on(db)
        stores.accounts.add(
            Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
        )
        try:
            stores.changes.append([_change(1)])
            _undone(db, lambda: stores.changes.append([_change(2)]))
            stores.changes.append([_change(3), _change(4)])
            read = stores.changes.after(["acc_1"], 0, limit=10)
            first = read[0].seq
            later = stores.changes.after(["acc_1"], first, limit=10)
        finally:
            db.close()
    assert [c.record.id for c in read] == ["msg_1", "msg_3", "msg_4"]
    assert read[1].seq > read[0].seq + 1
    assert [c.record.id for c in later] == ["msg_3", "msg_4"]


def test_undo_on_a_lost_connection_does_not_connect_again() -> None:
    with schema() as name:
        place = ServerPlace(server(name))
        try:
            conn, _ = place.open(26, 26)
            connects: list[object] = []
            sa.event.listen(conn.engine, "connect", lambda *_: connects.append(1))
            conn.invalidate()
            place.undo()
            assert connects == []
        finally:
            place.close()


def test_the_feed_counts_on_past_the_largest_integer() -> None:
    from psycopg import sql

    with schema() as name:
        db = database(name)
        stores = repositories_on(db)
        stores.accounts.add(
            Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
        )
        try:
            with connect() as admin:
                admin.execute(
                    sql.SQL(
                        "SELECT setval(pg_get_serial_sequence({}, 'seq'), {})"
                    ).format(sql.Literal(f"{name}.changes"), sql.Literal(2**31 - 1))
                )
            stores.changes.append([_change(1)])
            assert stores.changes.last() == 2**31
        finally:
            db.close()
