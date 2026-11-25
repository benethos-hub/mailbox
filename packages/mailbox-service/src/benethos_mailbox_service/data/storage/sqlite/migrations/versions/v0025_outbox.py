"""Schema 25: the outbox.

A send queued for later waits as a draft in the account's drafts folder.
A job says which draft, what it was when queued (a digest), the
Message-ID every attempt sends, and where it stands. It never holds
the mail. A job goes with its account. It keeps the user who queued it
without a reference, so a deleted user ends the job instead of the row.
The audit of sends names the job of an attempt.
"""

from __future__ import annotations

from ..migration import Migration


class V0025Outbox(Migration):
    version = 25
    statements = (
        """
        CREATE TABLE outbox (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            credential_id TEXT,
            operation TEXT NOT NULL,
            draft_id TEXT NOT NULL,
            digest TEXT NOT NULL,
            message_id_header TEXT NOT NULL,
            recipients TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            send_at TEXT,
            last_error TEXT,
            unclear_since TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT
        )
        """,
        "CREATE INDEX outbox_account ON outbox (account_id, created_at)",
        "CREATE INDEX outbox_state ON outbox (state, due_at)",
        "ALTER TABLE sends ADD COLUMN outbox_job_id TEXT",
    )
