"""What a program's database is: the description every module of the
group is handed, so the group knows no program and no schema by name.

A program builds its ``Shape`` at one place: its name, which keys the
lock of a running program on a server, its word in a text, its tables,
the folder of its revisions, its newest schema and the one its first
revision makes, the errors it has the group raise, and what is its own:
the steps a file took before the revisions, and what follows a fill.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa

from .errors import OWN, Errors
from .migrated import Migrated


class FileSteps(Protocol):
    """The steps a file of SQLite takes before the revisions begin, at the
    schema ``last``: a program that kept its schema so before."""

    @property
    def last(self) -> int:
        """The schema the steps reach, the baseline of the revisions."""
        ...

    def run(
        self,
        connection: sqlite3.Connection,
        path: Path | None,
        upto: int,
        newest: int,
        keep: bool,
        rewritten: bool,
    ) -> Migrated | None:
        """Bring the file on ``connection`` to ``upto``, or to ``last``
        when ``upto`` lies beyond, and say what was done, None when
        nothing. ``keep``: a copy of the file before a step that rebuilds
        tables. ``rewritten``: the file was rewritten to shrink, to be
        said. A file without the table ``meta`` and ``upto`` at ``last``
        or beyond is new: left to the revisions."""
        ...


@dataclass(frozen=True, slots=True)
class Shape:
    """The database of a program.

    ``program``: its name, such as ``benethos-mailbox-service``, which
    keys the lock of a running program on a server. ``noun``: how a text
    names it, such as ``service``. ``metadata``: its tables, among them
    ``meta`` with ``key`` and ``value``. ``versions``: the folder of its
    revisions. ``newest``: the schema of this version. ``baseline``: the
    schema its first revision makes. ``errors``: what the group raises.
    ``extra``: how the driver of PostgreSQL is installed, said when it is
    missing. ``set_aside``: where an operator reads how to set a schema
    that holds tables aside. ``file_steps``: the steps of a file before
    the revisions, None when there are none. ``filled``: what follows
    once rows were written into a table, such as a counter set on.
    """

    program: str
    noun: str
    metadata: sa.MetaData
    versions: Path
    newest: int
    baseline: int
    errors: Errors = OWN
    extra: str = (
        "storage postgres needs the extra postgres:"
        " pip install 'benethos-mailbox-common[postgres]'"
    )
    set_aside: str = ""
    file_steps: FileSteps | None = None
    filled: Callable[[sa.Connection], None] | None = None

    @property
    def meta(self) -> sa.Table:
        """The table ``meta``: the schema of the database, and what keeps
        account of it."""
        return self.metadata.tables["meta"]
