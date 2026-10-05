"""Schema 11: the last posts to each webhook, for its delivery log."""

from __future__ import annotations

from ..migration import Migration


class V0011WebhookAttempts(Migration):
    version = 11
    statements = (
        """
        CREATE TABLE webhook_attempts (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            delivery_id TEXT NOT NULL,
            at TEXT NOT NULL,
            events INTEGER NOT NULL,
            status INTEGER,
            error TEXT
        )
        """,
        "CREATE INDEX webhook_attempts_webhook ON webhook_attempts (webhook_id, seq)",
    )
