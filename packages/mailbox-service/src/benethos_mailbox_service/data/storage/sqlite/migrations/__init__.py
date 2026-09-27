"""The migrations of the schema, one module per version.

``vNN_<subject>.py`` takes the schema from version NN-1 to NN. A new
migration is a new module with the next number, added to ``MIGRATIONS``.
A migration that shipped in a release is never changed:
``RELEASED`` in the tests holds a hash of each.
"""

from __future__ import annotations

from . import (
    v01_accounts_users,
    v02_credentials,
    v03_message_index,
    v04_idempotency,
    v05_send_audit,
    v06_change_log,
    v07_webhooks,
    v08_idempotency_per_user,
    v09_passwords_unique_names,
    v10_last_sign_in,
    v11_webhook_attempts,
    v12_ui_sign_in,
    v13_webhooks_of_deleted_users,
)
from .step import Migration

MIGRATIONS: list[Migration] = [
    v01_accounts_users.MIGRATION,
    v02_credentials.MIGRATION,
    v03_message_index.MIGRATION,
    v04_idempotency.MIGRATION,
    v05_send_audit.MIGRATION,
    v06_change_log.MIGRATION,
    v07_webhooks.MIGRATION,
    v08_idempotency_per_user.MIGRATION,
    v09_passwords_unique_names.MIGRATION,
    v10_last_sign_in.MIGRATION,
    v11_webhook_attempts.MIGRATION,
    v12_ui_sign_in.MIGRATION,
    v13_webhooks_of_deleted_users.MIGRATION,
]

SCHEMA_VERSION = len(MIGRATIONS)

__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "Migration"]
