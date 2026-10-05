"""Schema 2: the wrapped data key and encrypted credentials."""

from __future__ import annotations

from .migration import Migration


class V0002Credentials(Migration):
    version = 2
    statements = (
        """
        CREATE TABLE keys (
            key_id TEXT PRIMARY KEY,
            nonce BLOB NOT NULL,
            ciphertext BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE credentials (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            field TEXT NOT NULL,
            key_id TEXT NOT NULL REFERENCES keys(key_id),
            nonce BLOB NOT NULL,
            ciphertext BLOB NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (account_id, field)
        )
        """,
    )
