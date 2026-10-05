"""The migrations of the schema, one class per version.

``vNNNN_<subject>.py`` holds the class that takes the schema from version
NNNN-1 to NNNN. A new migration is a class in a new module with the next
number, added to ``MIGRATIONS`` here, at its place. A migration that
shipped in a release is never changed: ``RELEASED`` in the tests holds
the fingerprint of each.
"""

from __future__ import annotations

from .migration import Migration
from .v0001_accounts_users import AccountsUsers
from .v0002_credentials import Credentials
from .v0003_message_index import MessageIndex
from .v0004_idempotency import Idempotency
from .v0005_send_audit import SendAudit
from .v0006_change_log import ChangeLog
from .v0007_webhooks import Webhooks
from .v0008_idempotency_per_user import IdempotencyPerUser
from .v0009_passwords_unique_names import PasswordsUniqueNames
from .v0010_last_sign_in import LastSignIn
from .v0011_webhook_attempts import WebhookAttempts
from .v0012_ui_sign_in import UiSignIn
from .v0013_webhooks_of_deleted_users import WebhooksOfDeletedUsers
from .v0014_service_rights import ServiceRights
from .v0015_service_rights_moved import ServiceRightsMoved
from .v0016_change_folders import ChangeFolders

MIGRATIONS: tuple[Migration, ...] = (
    AccountsUsers(),
    Credentials(),
    MessageIndex(),
    Idempotency(),
    SendAudit(),
    ChangeLog(),
    Webhooks(),
    IdempotencyPerUser(),
    PasswordsUniqueNames(),
    LastSignIn(),
    WebhookAttempts(),
    UiSignIn(),
    WebhooksOfDeletedUsers(),
    ServiceRights(),
    ServiceRightsMoved(),
    ChangeFolders(),
)

SCHEMA_VERSION = MIGRATIONS[-1].version

__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "Migration"]
