"""Schema 8: an Idempotency-Key counts per account and user. The results kept
are a cache of 24 hours, so the old ones are dropped.
"""

from __future__ import annotations

from .step import Migration

MIGRATION = Migration(
    [
        "DROP TABLE idempotency",
        """
        CREATE TABLE idempotency (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            operation TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (account_id, user_id, key)
        )
        """,
        "CREATE INDEX idempotency_created ON idempotency (created_at)",
    ],
)
