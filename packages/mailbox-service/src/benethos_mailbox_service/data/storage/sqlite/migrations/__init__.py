"""The migrations of the schema, one class per version.

``vNNNN_<subject>.py`` holds the class ``VNNNN<Subject>`` that takes the
schema from version NNNN-1 to NNNN. A new migration is a class in a new
module with the next number, added to ``MIGRATIONS`` here, at its place.
A migration that shipped in a release is never changed: ``RELEASED`` in
the tests holds the fingerprint of each.
"""

from __future__ import annotations

from .migration import Migration
from .v0001_accounts_users import V0001AccountsUsers
from .v0002_credentials import V0002Credentials
from .v0003_message_index import V0003MessageIndex
from .v0004_idempotency import V0004Idempotency
from .v0005_send_audit import V0005SendAudit
from .v0006_change_log import V0006ChangeLog
from .v0007_webhooks import V0007Webhooks
from .v0008_idempotency_per_user import V0008IdempotencyPerUser
from .v0009_passwords_unique_names import V0009PasswordsUniqueNames
from .v0010_last_sign_in import V0010LastSignIn
from .v0011_webhook_attempts import V0011WebhookAttempts
from .v0012_ui_sign_in import V0012UiSignIn
from .v0013_webhooks_of_deleted_users import V0013WebhooksOfDeletedUsers
from .v0014_service_rights import V0014ServiceRights
from .v0015_service_rights_moved import V0015ServiceRightsMoved
from .v0016_change_folders import V0016ChangeFolders

MIGRATIONS: tuple[Migration, ...] = (
    V0001AccountsUsers(),
    V0002Credentials(),
    V0003MessageIndex(),
    V0004Idempotency(),
    V0005SendAudit(),
    V0006ChangeLog(),
    V0007Webhooks(),
    V0008IdempotencyPerUser(),
    V0009PasswordsUniqueNames(),
    V0010LastSignIn(),
    V0011WebhookAttempts(),
    V0012UiSignIn(),
    V0013WebhooksOfDeletedUsers(),
    V0014ServiceRights(),
    V0015ServiceRightsMoved(),
    V0016ChangeFolders(),
)

SCHEMA_VERSION = MIGRATIONS[-1].version

__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "Migration"]
