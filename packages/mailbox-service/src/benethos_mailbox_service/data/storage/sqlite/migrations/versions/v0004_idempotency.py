"""Schema 4: results of requests with an Idempotency-Key."""

from __future__ import annotations

from ..migration import Migration


class V0004Idempotency(Migration):
    version = 4
    statements = (
        """
        CREATE TABLE idempotency (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            operation TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (account_id, key)
        )
        """,
        "CREATE INDEX idempotency_created ON idempotency (created_at)",
    )
