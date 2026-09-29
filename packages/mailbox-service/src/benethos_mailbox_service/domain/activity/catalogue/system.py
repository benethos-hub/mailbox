"""The area system: the service itself, its start, schema and stop, its
background loops, the recovery key, the log page, the keys and backups
of the host. What the assembly records is here as well (docs/LOGGING.md
5.1, 5.8)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ..base import Activity, Failure


@dataclass(frozen=True, kw_only=True)
class ServiceStarted(Activity):
    name: ClassVar[str] = "started"

    settings: str | None
    database: str | None
    schema: int | None

    def says(self) -> str:
        settings = self.settings or "the environment alone"
        if self.database is None:
            return f"started: settings from {settings}, storage in memory"
        return (
            f"started: settings from {settings}, database {self.database}, "
            f"schema {self.schema}"
        )


@dataclass(frozen=True, kw_only=True)
class SchemaMigrated(Activity):
    name: ClassVar[str] = "migrated"

    before: int
    after: int
    notes: tuple[str, ...] = ()

    def says(self) -> str:
        if self.before == 0:
            text = f"created the database with schema {self.after}"
        elif self.before == self.after:
            text = f"opened the database with schema {self.after}"
        else:
            text = f"migrated the database schema from {self.before} to {self.after}"
        return "; ".join([text, *self.notes])


@dataclass(frozen=True, kw_only=True)
class ServiceStopped(Activity):
    name: ClassVar[str] = "stopped"

    def says(self) -> str:
        return "stopped"


@dataclass(frozen=True, kw_only=True)
class LoopEnded(Failure):
    """A background loop that should run until the service stops."""

    name: ClassVar[str] = "loop_ended"
    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return "ended"


@dataclass(frozen=True, kw_only=True)
class RoundFailed(Failure):
    """A round of a background loop, which goes on with the next."""

    name: ClassVar[str] = "round_failed"
    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return "could not finish a round"


@dataclass(frozen=True, kw_only=True)
class MasterKeyFromEnvironment(Activity):
    name: ClassVar[str] = "key_from_env"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "takes the master key from MAILBOX_SERVICE_MASTER_KEY. The "
            "environment shows up in process listings and container inspection"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseShared(Activity):
    name: ClassVar[str] = "shared_db"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "found another service using this database: a restore cannot tell "
            "that this one runs"
        )


@dataclass(frozen=True, kw_only=True)
class RecoveryKeyShown(Activity):
    """The master key written out went to a person's screen."""

    name: ClassVar[str] = "recovery_shown"

    def says(self) -> str:
        return "was shown the recovery key in the UI"


@dataclass(frozen=True, kw_only=True)
class LogRead(Activity):
    """The log names users, addresses and accounts: who read it is
    logged, once per visit, not per page of it."""

    name: ClassVar[str] = "log_read"

    def says(self) -> str:
        return "read the service log"


@dataclass(frozen=True, kw_only=True)
class KeysCreated(Activity):
    name: ClassVar[str] = "keys_created"

    def says(self) -> str:
        return "created the master key and the data key"


@dataclass(frozen=True, kw_only=True)
class MasterKeyStored(Activity):
    name: ClassVar[str] = "key_imported"

    def says(self) -> str:
        return "stored the master key from a recovery key"


@dataclass(frozen=True, kw_only=True)
class BackupWritten(Activity):
    name: ClassVar[str] = "backup_written"

    file: str
    schema: int

    def says(self) -> str:
        return f"wrote a backup to {self.file}, schema {self.schema}"


@dataclass(frozen=True, kw_only=True)
class BackupRestored(Activity):
    name: ClassVar[str] = "backup_restored"

    file: str
    schema: int
    # When the backup was made, as its manifest says.
    made: str

    def says(self) -> str:
        return f"restored the backup {self.file} of {self.made}, schema {self.schema}"
