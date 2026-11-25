"""Schema 26: the order of every list is held in a column.

The order in which index entries and thread links came was the hidden
``rowid`` of SQLite, which no other database has. Both tables are built
anew with a key ``seq`` that counts up, the rows taking their ``rowid``
as ``seq``, so the order stays as it was. The rebuild needs free space
of the size of the index once.
"""

from __future__ import annotations

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
    )
