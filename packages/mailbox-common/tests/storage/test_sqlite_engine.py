"""The engine on one SQLite connection: a writer begins at once, a
reader plainly, asking for no lock to write."""

from __future__ import annotations

import sqlite3

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect
from benethos_mailbox_common.storage.file_place import sqlite_engine


def test_a_writer_begins_at_once_and_a_reader_plainly() -> None:
    writer = sqlite_engine(lambda: sqlite3.connect(":memory:"))
    reader = sqlite_engine(lambda: sqlite3.connect(":memory:"), writer=False)
    try:
        assert sa.event.contains(writer, "begin", dialect.begin_at_once)
        assert not sa.event.contains(reader, "begin", dialect.begin_at_once)
    finally:
        writer.dispose()
        reader.dispose()
