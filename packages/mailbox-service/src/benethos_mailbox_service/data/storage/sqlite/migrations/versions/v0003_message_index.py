"""Schema 3: the id mapping and the state of each folder."""

from __future__ import annotations

from ..migration import Migration


class V0003MessageIndex(Migration):
    version = 3
    statements = (
        """
        CREATE TABLE message_index (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            id TEXT NOT NULL,
            native_id TEXT NOT NULL,
            folder_id TEXT NOT NULL,
            header TEXT,
            PRIMARY KEY (account_id, id),
            UNIQUE (account_id, native_id)
        )
        """,
        "CREATE INDEX message_index_folder ON message_index (account_id, folder_id)",
        """
        CREATE TABLE folder_states (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            folder_id TEXT NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (account_id, folder_id)
        )
        """,
    )
