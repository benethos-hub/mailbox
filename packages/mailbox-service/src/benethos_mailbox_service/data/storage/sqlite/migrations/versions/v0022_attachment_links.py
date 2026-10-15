"""Schema 22: links to an attachment (CONCEPT 6.3).

A link lets another service fetch one attachment once, for a short
time, without a token of this service. The secret is kept as its
digest only, as a token is. A link goes with its account and with the
token that made it. The purge removes the links used or ended.
"""

from __future__ import annotations

from ..migration import Migration


class V0022AttachmentLinks(Migration):
    version = 22
    statements = (
        """
        CREATE TABLE attachment_links (
            id TEXT PRIMARY KEY,
            secret_hash TEXT NOT NULL UNIQUE,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            message_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL,
            token_id TEXT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            redeemed_at TEXT,
            redeemed_by TEXT
        )
        """,
        "CREATE INDEX attachment_links_expires ON attachment_links (expires_at)",
    )
