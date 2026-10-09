"""Schema 18: a second factor for the UI sign-in (docs/AUTHENTICATION.md).
The devices of a user, each with a TOTP secret sealed with the data key,
and the hashes of the user's recovery codes. Both go with the user.
"""

from __future__ import annotations

from ..migration import Migration


class V0018SecondFactor(Migration):
    version = 18
    statements = (
        """
        CREATE TABLE totp_devices (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            key_id TEXT NOT NULL,
            nonce BLOB NOT NULL,
            ciphertext BLOB NOT NULL,
            created_at TEXT NOT NULL,
            last_step INTEGER,
            last_used_at TEXT
        )
        """,
        "CREATE INDEX totp_devices_user ON totp_devices (user_id)",
        """
        CREATE TABLE recovery_codes (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            hash TEXT NOT NULL,
            used_at TEXT,
            PRIMARY KEY (user_id, hash)
        )
        """,
    )
