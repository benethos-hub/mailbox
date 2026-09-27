"""Schema 10: when a user last signed in to the UI."""

from __future__ import annotations

from .step import Migration

MIGRATION = Migration(
    [
        "ALTER TABLE passwords ADD COLUMN last_sign_in_at TEXT",
    ],
)
