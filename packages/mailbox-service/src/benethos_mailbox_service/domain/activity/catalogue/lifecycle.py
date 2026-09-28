"""The life of the process: start, schema, stop, background loops
(docs/LOGGING.md 5.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ..base import Activity, Failure


@dataclass(frozen=True, kw_only=True)
class ServiceStarted(Activity):
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
    before: int
    after: int
    notes: tuple[str, ...] = ()

    def says(self) -> str:
        if self.before == 0:
            text = f"created the database with schema {self.after}"
        else:
            text = f"migrated the database schema from {self.before} to {self.after}"
        return "; ".join([text, *self.notes])


@dataclass(frozen=True, kw_only=True)
class ServiceStopped(Activity):
    def says(self) -> str:
        return "stopped"


@dataclass(frozen=True, kw_only=True)
class LoopEnded(Failure):
    """A background loop that should run until the service stops."""

    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return "ended"


@dataclass(frozen=True, kw_only=True)
class RoundFailed(Failure):
    """A round of a background loop, which goes on with the next."""

    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return "could not finish a round"


@dataclass(frozen=True, kw_only=True)
class MasterKeyFromEnvironment(Activity):
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "takes the master key from MAILBOX_SERVICE_MASTER_KEY. The "
            "environment shows up in process listings and container inspection"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseShared(Activity):
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "found another service using this database: a restore cannot tell "
            "that this one runs"
        )
