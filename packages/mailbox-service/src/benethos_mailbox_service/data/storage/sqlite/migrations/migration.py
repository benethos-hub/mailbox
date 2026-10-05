"""What one migration is: a class of this base, one per module."""

from __future__ import annotations

import hashlib
import sqlite3
from abc import ABC
from typing import ClassVar


class Migration(ABC):
    """The step from schema version - 1 to version, in one transaction.
    ``statements`` are single SQL statements, run in order. ``before``
    runs first and returns what to log once the step is committed.
    A step that shipped in a release is never changed: the tests hold
    its ``fingerprint``."""

    version: ClassVar[int]
    statements: ClassVar[tuple[str, ...]]

    def before(self, db: sqlite3.Connection) -> list[str]:
        """Runs first, for what SQL alone cannot do or say."""
        return []

    def apply(self, db: sqlite3.Connection) -> list[str]:
        """The step, as the database runs it: ``before``, then the
        statements. What ``before`` had to say."""
        said = self.before(db)
        for statement in self.statements:
            db.execute(statement)
        return said

    @classmethod
    def fingerprint(cls) -> str:
        """A hash of the statements, by which a released step is frozen."""
        return hashlib.sha256("\n;\n".join(cls.statements).encode()).hexdigest()
