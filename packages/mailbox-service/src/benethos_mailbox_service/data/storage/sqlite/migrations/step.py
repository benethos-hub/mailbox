"""What one migration is: its statements, and a step before them."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    """The step from one schema version to the next, in one transaction.
    ``statements`` are single SQL statements, run in order. ``before``
    runs first and returns what to log once the step is committed."""

    statements: list[str]
    before: Callable[[sqlite3.Connection], list[str]] | None = None
