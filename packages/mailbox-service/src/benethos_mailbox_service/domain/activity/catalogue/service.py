"""The service itself: recovery key, log page, keys, backups, discovery
(docs/LOGGING.md 5.8)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ..base import Activity, plural


@dataclass(frozen=True, kw_only=True)
class RecoveryKeyShown(Activity):
    """The master key written out went to a person's screen."""

    def says(self) -> str:
        return "was shown the recovery key in the UI"


@dataclass(frozen=True, kw_only=True)
class LogRead(Activity):
    """The log names users, addresses and accounts: who read it is
    logged, once per visit, not per page of it."""

    def says(self) -> str:
        return "read the service log"


@dataclass(frozen=True, kw_only=True)
class Discovered(Activity):
    """The domain alone: the local part of the address is the person's."""

    level: ClassVar[int] = logging.DEBUG

    domain: str
    candidates: int
    sources: int

    def says(self) -> str:
        return (
            f"looked up the servers of {self.domain}: "
            f"{plural(self.candidates, 'candidate')} from "
            f"{plural(self.sources, 'source')}"
        )


@dataclass(frozen=True, kw_only=True)
class KeysCreated(Activity):
    def says(self) -> str:
        return "created the master key and the data key"


@dataclass(frozen=True, kw_only=True)
class MasterKeyStored(Activity):
    def says(self) -> str:
        return "stored the master key from a recovery key"


@dataclass(frozen=True, kw_only=True)
class BackupWritten(Activity):
    file: str
    schema: int

    def says(self) -> str:
        return f"wrote a backup to {self.file}, schema {self.schema}"


@dataclass(frozen=True, kw_only=True)
class BackupRestored(Activity):
    file: str
    schema: int
    # When the backup was made, as its manifest says.
    made: str

    def says(self) -> str:
        return f"restored the backup {self.file} of {self.made}, schema {self.schema}"
