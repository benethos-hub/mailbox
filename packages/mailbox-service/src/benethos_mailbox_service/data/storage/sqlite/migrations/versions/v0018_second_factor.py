"""Schema 18: a second factor for the UI sign-in (docs/AUTHENTICATION.md).
The TOTP secret of a user, sealed with the data key, and the hashes of
its recovery codes. Both go with the user.
"""

from __future__ import annotations

from ..migration import Migration


class V0018SecondFactor(Migration):
    version = 18
    statements = (
        """
        CREATE TABLE totp (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            key_id TEXT NOT NULL,
            nonce BLOB NOT NULL,
            ciphertext BLOB NOT NULL,
            confirmed_at TEXT NOT NULL,
            last_step INTEGER
        )
        """,
        """
        CREATE TABLE recovery_codes (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            hash TEXT NOT NULL,
            used_at TEXT,
            PRIMARY KEY (user_id, hash)
        )
        """,
    )
