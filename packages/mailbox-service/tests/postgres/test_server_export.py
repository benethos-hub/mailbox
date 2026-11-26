"""The logical export on PostgreSQL: an export of a database in SQLite is
read into a schema on the server and is the same table for table, and a
feed whose newest rows were purged counts on after it."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import sqlalchemy as sa

from benethos_mailbox_service.data.export import read_export, write_export
from benethos_mailbox_service.data.models import ChangeRecord
from benethos_mailbox_service.data.storage import Database, repositories_on

from ..postgres_helpers import database, schema
from ..schema_helpers import run


def _exported(db: Database) -> bytes:
    out = io.BytesIO()
    write_export(db, out)
    return out.getvalue()


def test_an_export_is_read_into_a_schema_table_for_table(source: Database) -> None:
    data = _exported(source)
    with schema() as name:
        target = database(name)
        try:
            counts = read_export(io.BytesIO(data), target)
            assert all(counts.values()), "a table left empty"
            for table in source.tables():
                assert list(target.rows(table.name)) == list(source.rows(table.name)), (
                    table.name
                )
            assert _exported(target) == data
        finally:
            target.close()


def test_a_purged_feed_counts_on_after_an_export(source: Database) -> None:
    record = ChangeRecord(
        type="message.created",
        id="msg_1",
        account_id="acc_seed2",
        at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repositories_on(source).changes.append([record, record])
    run(source, "DELETE FROM changes WHERE seq > 7")
    data = _exported(source)
    with schema() as name:
        target = database(name)
        try:
            read_export(io.BytesIO(data), target)
            repositories_on(target).changes.append([record])
            numbers = [row[0] for row in target.rows("changes")]
        finally:
            target.close()
    assert numbers == [5, 7, 12]


def test_every_counting_key_counts_on_after_an_export(source: Database) -> None:
    """The rows keep their numbers, and the sequence behind each counting
    key hands out a higher one afterwards."""
    data = _exported(source)
    counted = {"changes", "message_index", "thread_links", "webhook_attempts"}
    with schema() as name:
        target = database(name)
        try:
            read_export(io.BytesIO(data), target)
            with target.connected() as conn:
                for table in sorted(counted):
                    top = conn.execute(
                        sa.text(f"SELECT max(seq) FROM {table}")
                    ).scalar()
                    following = conn.execute(
                        sa.text(
                            f"SELECT nextval(pg_get_serial_sequence('{table}', 'seq'))"
                        )
                    ).scalar()
                    assert top and following > top, table
                conn.rollback()
        finally:
            target.close()
