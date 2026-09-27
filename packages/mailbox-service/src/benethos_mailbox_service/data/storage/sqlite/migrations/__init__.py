"""The migrations of the schema, one module per version.

``vNNNN_<subject>.py`` takes the schema from version NNNN-1 to NNNN. A new
migration is a new module with the next number, added to ``MIGRATIONS``.
A migration that shipped in a release is never changed:
``RELEASED`` in the tests holds a hash of each.
"""

from __future__ import annotations

from . import (
    v0001_accounts_users,
    v0002_credentials,
    v0003_message_index,
    v0004_idempotency,
    v0005_send_audit,
    v0006_change_log,
    v0007_webhooks,
    v0008_idempotency_per_user,
    v0009_passwords_unique_names,
    v0010_last_sign_in,
    v0011_webhook_attempts,
    v0012_ui_sign_in,
    v0013_webhooks_of_deleted_users,
)
from .step import Migration

MIGRATIONS: list[Migration] = [
    v0001_accounts_users.MIGRATION,
    v0002_credentials.MIGRATION,
    v0003_message_index.MIGRATION,
    v0004_idempotency.MIGRATION,
    v0005_send_audit.MIGRATION,
    v0006_change_log.MIGRATION,
    v0007_webhooks.MIGRATION,
    v0008_idempotency_per_user.MIGRATION,
    v0009_passwords_unique_names.MIGRATION,
    v0010_last_sign_in.MIGRATION,
    v0011_webhook_attempts.MIGRATION,
    v0012_ui_sign_in.MIGRATION,
    v0013_webhooks_of_deleted_users.MIGRATION,
]

SCHEMA_VERSION = len(MIGRATIONS)

__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "Migration"]
