"""Schema 6: the change log behind the change feed."""

from __future__ import annotations

from .migration import Migration


class ChangeLog(Migration):
    version = 6
    statements = (
        """
        CREATE TABLE changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            message_id TEXT NOT NULL,
            type TEXT NOT NULL,
            at TEXT NOT NULL
        )
        """,
        "CREATE INDEX changes_account ON changes (account_id, seq)",
        "CREATE INDEX changes_at ON changes (at)",
    )
