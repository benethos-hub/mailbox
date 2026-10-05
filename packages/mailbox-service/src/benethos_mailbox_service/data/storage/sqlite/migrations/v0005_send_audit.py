"""Schema 5: the audit of sends. It outlives its account and user, so no references."""

from __future__ import annotations

from .migration import Migration


class V0005SendAudit(Migration):
    version = 5
    statements = (
        """
        CREATE TABLE sends (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            user_id TEXT NOT NULL,
            credential_id TEXT,
            account_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            recipients TEXT NOT NULL,
            outcome TEXT NOT NULL,
            error TEXT,
            refused TEXT NOT NULL,
            message_id_header TEXT
        )
        """,
        "CREATE INDEX sends_account ON sends (account_id, created_at)",
        "CREATE INDEX sends_user ON sends (user_id, account_id, created_at)",
    )
