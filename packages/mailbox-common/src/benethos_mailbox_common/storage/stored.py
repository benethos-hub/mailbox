"""What holds a program's records, as the tools that copy them see it:
``Records``, its tables and rows, and ``Store``, the whole store, which
a database is and a program's own may be."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from .errors import StorageUnavailableError
from .migrated import Migrated
from .outage import Availability
from .tables import Table


class Records(Protocol):
    """The records of a store, table by table, for an export."""

    def schema_version(self) -> int:
        """The version of the schema the records are in."""
        ...

    def tables(self) -> list[Table]:
        """Every table of the schema with its columns and key, each after
        the tables it refers to."""
        ...

    def rows(self, table: str) -> Iterator[tuple[Any, ...]]:
        """The rows of a table of ``tables`` in the order of its key, read
        in chunks."""
        ...


class Store(Records, Protocol):
    """What holds the records of all repositories: a fixed view of them
    for a backup, the mark of a running program, and closing."""

    def unavailable(self) -> StorageUnavailableError | None:
        """The error a call meets now, without asking the database: None
        unless it is known to be away."""
        ...

    def watch(self, report: Callable[[Availability], None]) -> None:
        """``report`` hears of each change of whether the database can be
        reached."""
        ...

    def view(self) -> AbstractContextManager[Records]:
        """The records at one moment, taken while the store is in use,
        for the time of the block."""
        ...

    def snapshot_file(self) -> AbstractContextManager[Path]:
        """For a store that is a file: a consistent copy of it, taken
        while it is in use, readable by its owner alone, gone when the
        block ends. Another store has none and raises its failure."""
        ...

    def transaction(self) -> AbstractContextManager[object]:
        """One transaction over every repository of the store. Inside
        another one, a part of it that is undone alone."""
        ...

    def serving(self) -> AbstractContextManager[bool]:
        """Mark the store as used by a running program while the block
        runs. A file yields False when another one marked it already, a
        server raises the error of a database in use."""
        ...

    def close(self) -> None: ...

    def fill(
        self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
    ) -> int:
        """Write ``rows`` into ``table``, which holds none yet. How many."""
        ...

    def mark_move(self, started: str | None) -> None:
        """Mark the store as the target of a move or a restore that began
        at ``started``, or, with None, as one that ended."""
        ...

    @property
    def migrated(self) -> Migrated | None:
        """What opening the store did to its schema, None when nothing."""
        ...
