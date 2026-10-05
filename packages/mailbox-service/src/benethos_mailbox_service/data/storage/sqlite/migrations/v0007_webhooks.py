"""Schema 7: webhooks, their sealed secret and where their delivery stands."""

from __future__ import annotations

from .migration import Migration


class V0007Webhooks(Migration):
    version = 7
    statements = (
        """
        CREATE TABLE webhooks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            events TEXT NOT NULL,
            accounts TEXT,
            created_at TEXT NOT NULL,
            key_id TEXT NOT NULL REFERENCES keys(key_id),
            nonce BLOB NOT NULL,
            ciphertext BLOB NOT NULL,
            cursor INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            last_delivery_at TEXT,
            last_error TEXT
        )
        """,
    )
