"""One step of the schema of a state file."""

from __future__ import annotations

import hashlib
import inspect
import sqlite3
import sys
from abc import ABC
from typing import ClassVar

__all__ = ["Migration"]


class Migration(ABC):
    """The step from schema version - 1 to ``version``, in one transaction.

    ``statements`` are single SQL statements, run in order, each with the
    indentation of its module taken off. ``before`` runs
    first, for a step that needs Python, and answers what to note once the
    step is committed. A step that shipped in a release is never changed,
    down to a comment: the tests hold its ``fingerprint``.
    """

    version: ClassVar[int]
    statements: ClassVar[tuple[str, ...]] = ()

    def before(self, db: sqlite3.Connection) -> list[str]:
        """A step in Python, run before the statements. Answers notes."""
        return []

    def apply(self, db: sqlite3.Connection) -> list[str]:
        """Run the step on ``db``, inside the caller's transaction."""
        said = self.before(db)
        for statement in self.statements:
            db.execute(inspect.cleandoc(statement))
        return said

    @classmethod
    def fingerprint(cls) -> str:
        """The sha256 of the step's whole module, comments included."""
        source = inspect.getsource(sys.modules[cls.__module__])
        return hashlib.sha256(source.encode()).hexdigest()
