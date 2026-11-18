"""Schema 23: passkeys, a second method of the second factor
(docs/AUTHENTICATION.md 5, 7).

A passkey holds a public key and the counter of its last signature. No
secret: it is stored as it is, not sealed. A credential id is stored
once across all users. The passkeys go with their user.
"""

from __future__ import annotations

from ..migration import Migration


class V0023Passkeys(Migration):
    version = 23
    statements = (
        """
        CREATE TABLE passkeys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            credential_id BLOB NOT NULL UNIQUE,
            credential BLOB NOT NULL,
            sign_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_used_at TEXT
        )
        """,
        "CREATE INDEX passkeys_user ON passkeys (user_id)",
    )
