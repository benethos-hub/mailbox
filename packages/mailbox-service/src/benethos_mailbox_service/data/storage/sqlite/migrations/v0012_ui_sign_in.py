"""Schema 12: whether a user may sign in to the UI. Those with a password so
far keep it, those without are API users.
"""

from __future__ import annotations

from .step import Migration

MIGRATION = Migration(
    [
        "ALTER TABLE users ADD COLUMN ui_sign_in INTEGER NOT NULL DEFAULT 0",
        "UPDATE users SET ui_sign_in = 1 WHERE id IN (SELECT user_id FROM passwords)",
    ],
)
