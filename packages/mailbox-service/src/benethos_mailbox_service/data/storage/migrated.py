"""What opening a database did to its schema, of no database in
particular: the old steps of ``sqlite/`` say it, and the revisions of
``sql/``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migrated:
    """What opening the database did to its schema, for the log: the
    versions before and after, and what the migrations had to say."""

    before: int
    after: int
    notes: tuple[str, ...] = ()
