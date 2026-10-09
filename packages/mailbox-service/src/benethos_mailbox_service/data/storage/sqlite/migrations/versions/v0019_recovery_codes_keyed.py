"""Schema 19: recovery codes hashed with HMAC-SHA256 under a key derived
from the data key, with the user's id in what is hashed
(docs/AUTHENTICATION.md 6). A stolen database alone no longer lets
anyone try guesses against them, and a guess fits one user only.

The plain SHA-256 hashes of schema 18 cannot become the new ones, since
the codes themselves are never kept. So they are deleted, and a user
with a second factor makes new codes. No release held schema 18 then.
"""

from __future__ import annotations

from ..migration import Migration


class V0019RecoveryCodesKeyed(Migration):
    version = 19
    statements = (
        "DROP TABLE recovery_codes",
        """
        CREATE TABLE recovery_codes (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key_id TEXT NOT NULL,
            hash TEXT NOT NULL,
            used_at TEXT,
            PRIMARY KEY (user_id, hash)
        )
        """,
    )
