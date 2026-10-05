"""Schema 17: the audit of administration (docs/AUDIT.md). Who signed in,
and who changed users, tokens, roles, accounts and webhooks. It outlives
its users and accounts, so no references."""

from __future__ import annotations

from ..migration import Migration


class V0017Activity(Migration):
    version = 17
    statements = (
        """
        CREATE TABLE activity (
            id TEXT PRIMARY KEY,
            at TEXT NOT NULL,
            activity TEXT NOT NULL,
            user_id TEXT,
            user_name TEXT NOT NULL,
            credential TEXT,
            record TEXT,
            source TEXT,
            outcome TEXT NOT NULL,
            detail TEXT NOT NULL
        )
        """,
        "CREATE INDEX activity_at ON activity (at)",
        "CREATE INDEX activity_user ON activity (user_id, at)",
        "CREATE INDEX activity_record ON activity (record, at)",
    )
