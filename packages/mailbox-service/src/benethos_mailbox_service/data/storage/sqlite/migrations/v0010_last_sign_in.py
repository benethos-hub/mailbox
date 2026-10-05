"""Schema 10: when a user last signed in to the UI."""

from __future__ import annotations

from .migration import Migration


class V0010LastSignIn(Migration):
    version = 10
    statements = ("ALTER TABLE passwords ADD COLUMN last_sign_in_at TEXT",)
