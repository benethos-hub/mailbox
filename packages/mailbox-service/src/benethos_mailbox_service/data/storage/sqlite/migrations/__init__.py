"""The migrations of the schema, one class per version, in one registry.

``versions/vNNNN_<subject>.py`` holds the class ``VNNNN<Subject>`` that
takes the schema from version NNNN-1 to NNNN. A new migration is a class
in a new module there with the next number, added to ``MIGRATIONS`` here,
at its place.
The registry refuses a gap or a wrong place. A migration that shipped in
a release is never changed: ``RELEASED`` in the tests holds the
fingerprint of each.
"""

from __future__ import annotations

from .migration import Migration
from .registry import MigrationRegistry
from .versions.v0001_accounts_users import V0001AccountsUsers
from .versions.v0002_credentials import V0002Credentials
from .versions.v0003_message_index import V0003MessageIndex
from .versions.v0004_idempotency import V0004Idempotency
from .versions.v0005_send_audit import V0005SendAudit
from .versions.v0006_change_log import V0006ChangeLog
from .versions.v0007_webhooks import V0007Webhooks
from .versions.v0008_idempotency_per_user import V0008IdempotencyPerUser
from .versions.v0009_passwords_unique_names import V0009PasswordsUniqueNames
from .versions.v0010_last_sign_in import V0010LastSignIn
from .versions.v0011_webhook_attempts import V0011WebhookAttempts
from .versions.v0012_ui_sign_in import V0012UiSignIn
from .versions.v0013_webhooks_of_deleted_users import V0013WebhooksOfDeletedUsers
from .versions.v0014_service_rights import V0014ServiceRights
from .versions.v0015_service_rights_moved import V0015ServiceRightsMoved
from .versions.v0016_change_folders import V0016ChangeFolders
from .versions.v0017_activity import V0017Activity
from .versions.v0018_second_factor import V0018SecondFactor
from .versions.v0019_recovery_codes_keyed import V0019RecoveryCodesKeyed

MIGRATIONS = MigrationRegistry(
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
    V0017Activity(),
    V0018SecondFactor(),
    V0019RecoveryCodesKeyed(),
)

SCHEMA_VERSION = MIGRATIONS.schema_version

__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "Migration", "MigrationRegistry"]
