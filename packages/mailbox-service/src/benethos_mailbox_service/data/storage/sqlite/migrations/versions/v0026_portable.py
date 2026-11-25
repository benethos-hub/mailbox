"""Schema 26: the order of every list is held in a column.

The order in which index entries and thread links came was the hidden
``rowid`` of SQLite, which no other database has. Both tables are built
anew with a key ``seq`` that counts up, the rows taking their ``rowid``
as ``seq``, so the order stays as it was. The rebuild needs free space
of the size of the index once.

Accounts, users and roles were listed in the order of their ``rowid``
as well. Each gets a column ``position``, filled from it.

The active key was the last row of ``keys`` by ``rowid``, the last
number of the change feed was read from ``sqlite_sequence``. Both are
written to ``meta`` now, as ``active_key`` and ``changes_last``. Not
the newest ``created_at``: a clock set back would make an old key the
active one.

User names were unique by ``COLLATE NOCASE``, a collation of SQLite.
A column ``name_lower`` holds the name with its ASCII letters in lower
case, which is what ``lower()`` and ``NOCASE`` fold, with the unique
index on it. So no name is renamed. The domain compares names with
``casefold()`` and refuses a second one beyond ASCII, as before.

The audit of sends was searched by recipient through ``json_each`` and
a function ``casefold`` the service gave SQLite. A column
``recipients_folded`` holds the addresses, each folded by
``str.casefold()``, one per line. ``before`` folds them into a table of
its own for this step, since SQL cannot.
"""

from __future__ import annotations

import json
import sqlite3

from ..migration import Migration


class V0026Portable(Migration):
    version = 26
    statements = (
        """
        CREATE TABLE message_index_new (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            id TEXT NOT NULL,
            native_id TEXT NOT NULL,
            folder_id TEXT NOT NULL,
            header TEXT,
            thread_id TEXT,
            UNIQUE (account_id, id),
            UNIQUE (account_id, native_id)
        )
        """,
        """
        INSERT INTO message_index_new
            (seq, account_id, id, native_id, folder_id, header, thread_id)
            SELECT rowid, account_id, id, native_id, folder_id, header, thread_id
            FROM message_index ORDER BY rowid
        """,
        "DROP TABLE message_index",
        "ALTER TABLE message_index_new RENAME TO message_index",
        "CREATE INDEX message_index_folder ON message_index (account_id, folder_id)",
        "CREATE INDEX message_index_thread ON message_index (account_id, thread_id)",
        "CREATE INDEX message_index_header ON message_index (account_id, header)",
        """
        CREATE TABLE thread_links_new (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            header TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            UNIQUE (account_id, header)
        )
        """,
        """
        INSERT INTO thread_links_new (seq, account_id, header, thread_id)
            SELECT rowid, account_id, header, thread_id
            FROM thread_links ORDER BY rowid
        """,
        "DROP TABLE thread_links",
        "ALTER TABLE thread_links_new RENAME TO thread_links",
        "CREATE INDEX thread_links_thread ON thread_links (account_id, thread_id)",
        "ALTER TABLE accounts ADD COLUMN position INTEGER",
        "UPDATE accounts SET position = rowid",
        "CREATE UNIQUE INDEX accounts_position ON accounts (position)",
        "ALTER TABLE users ADD COLUMN position INTEGER",
        "UPDATE users SET position = rowid",
        "CREATE UNIQUE INDEX users_position ON users (position)",
        "ALTER TABLE roles ADD COLUMN position INTEGER",
        "UPDATE roles SET position = rowid",
        "CREATE UNIQUE INDEX roles_position ON roles (position)",
        """
        INSERT INTO meta (key, value)
            SELECT 'active_key', key_id FROM keys ORDER BY rowid DESC LIMIT 1
        """,
        """
        INSERT INTO meta (key, value) VALUES ('changes_last', CAST(COALESCE(
            (SELECT seq FROM sqlite_sequence WHERE name = 'changes'), 0) AS TEXT))
        """,
        "ALTER TABLE users ADD COLUMN name_lower TEXT",
        "UPDATE users SET name_lower = lower(name)",
        "DROP INDEX users_name",
        "CREATE UNIQUE INDEX users_name_lower ON users (name_lower)",
        "ALTER TABLE sends ADD COLUMN recipients_folded TEXT NOT NULL DEFAULT ''",
        """
        UPDATE sends SET recipients_folded = COALESCE(
            (SELECT value FROM temp.sends_folded WHERE id = sends.id), '')
        """,
        "DROP TABLE temp.sends_folded",
    )

    def before(self, db: sqlite3.Connection) -> list[str]:
        """The recipients of every send, folded, for the statements."""
        db.execute("CREATE TEMP TABLE sends_folded (id TEXT PRIMARY KEY, value TEXT)")
        rows = db.execute("SELECT id, recipients FROM sends").fetchall()
        db.executemany(
            "INSERT INTO temp.sends_folded (id, value) VALUES (?, ?)",
            [
                (row[0], "\n".join(a.casefold() for a in json.loads(row[1])))
                for row in rows
            ],
        )
        return []
