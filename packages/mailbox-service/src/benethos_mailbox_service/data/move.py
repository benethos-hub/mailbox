"""The move of the records from one database to another, the file of
SQLite to a schema on PostgreSQL or back (``storage move``).

Before anything is written, every value of the source is held to the
kind of its column: SQLite keeps a text in a column of numbers or of
bytes, which PostgreSQL refuses or takes as something else. A value that
does not fit stops the move. The message names the table, the column and
how many, never a value.

The target must be empty: a file that is not there yet, or a schema
without tables. Both sides are locked as a running service locks them,
so neither runs meanwhile. A mark in ``meta`` says a move is writing, and
a database with it is not opened. The tables are copied from a view of
the source at one moment, in the order of their references, then each is
counted and summed on both sides, read anew, and only then the mark
goes. The source is never written to.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from benethos_mailbox_common.paths import locks

from ..common.clock import iso, utc_now
from ..errors import StorageInUseError
from .export import row_line
from .storage import (
    MOVING,
    SCHEMA_VERSION,
    SET_ASIDE,
    Database,
    Records,
    Server,
    ServerPlace,
    inspect_file,
    service_lock,
)

_FITS: dict[str, type] = {"text": str, "number": int, "bytes": bytes}


class MoveError(Exception):
    """A move that cannot be made or did not hold: what is wrong, never a
    value of a row."""


@dataclass(frozen=True, slots=True)
class Misfit:
    """How many values of ``column`` of ``table`` do not fit its kind."""

    table: str
    column: str
    count: int


def misfits(records: Records) -> list[Misfit]:
    """Each column of ``records`` with values that do not fit its kind,
    table by table in the order of their references."""
    found: list[Misfit] = []
    for table in records.tables():
        fits = [_FITS[kind] for kind in table.kinds]
        counts = [0] * len(fits)
        for row in records.rows(table.name):
            for index, value in enumerate(row):
                if value is not None and not isinstance(value, fits[index]):
                    counts[index] += 1
        found += [
            Misfit(table.name, column, count)
            for column, count in zip(table.columns, counts, strict=True)
            if count
        ]
    return found


def refused(found: list[Misfit]) -> MoveError:
    """The error that stops a move for ``found``, one line per column."""
    lines = [f"  {f.table}.{f.column}: {f.count}" for f in found]
    return MoveError(
        "values that do not fit their column, nothing was written:\n" + "\n".join(lines)
    )


@dataclass(frozen=True, slots=True)
class Moved:
    """What a move copied, or a check found fitting: the tables and the
    rows in them."""

    tables: int
    rows: int


@dataclass(frozen=True, slots=True)
class _Sum:
    rows: int
    sha256: str


def check_move(source: Path | Server) -> Moved:
    """Hold every value of ``source`` to its column, writing nothing.
    MoveError names what does not fit."""
    with _source(source) as db, db.view() as records:
        found = misfits(records)
        if found:
            raise refused(found)
        sums = _sums(records)
    return _moved(sums)


def move_records(source: Path | Server, target: Path | Server) -> Moved:
    """Every record of ``source`` into ``target``, which holds none yet,
    checked first and compared after. MoveError when it cannot be made or
    did not hold: then the target keeps the mark and is not opened."""
    if isinstance(target, Path):
        _not_there(target)
    with ExitStack() as held:
        db = held.enter_context(_source(source))
        records = held.enter_context(db.view())
        found = misfits(records)
        if found:
            raise refused(found)
        made = held.enter_context(_target(target))
        made.mark_move(iso(utc_now()))
        for table in records.tables():
            made.fill(table.name, table.columns, records.rows(table.name))
        sums = _sums(records)
        written = _sums(made)
        differ = sorted(name for name in sums if written.get(name) != sums[name])
        if differ:
            raise MoveError(
                "the copy does not match its source in the tables "
                + ", ".join(differ)
                + ": the target keeps the mark of a move that did not finish"
            )
        made.mark_move(None)
    return _moved(sums)


@contextmanager
def _source(side: Path | Server) -> Iterator[Database]:
    """The database at ``side``, at this version's schema, locked."""
    if isinstance(side, Path):
        if not side.exists():
            raise MoveError(f"there is no database at {side}")
        try:
            _current(inspect_file(side))
        except ValueError as exc:
            raise MoveError(f"the database at {side} is unsound: {exc}") from None
        with _file_locked(side):
            db = Database(side, keep_copy=False)
            try:
                yield db
            finally:
                db.close()
        return
    with _server(side) as place:
        if not place.tables():
            raise MoveError(f"the schema {side.schema_name} holds no database")
        _current(place.held_schema())
        yield Database(place=place)


@contextmanager
def _target(side: Path | Server) -> Iterator[Database]:
    """A new database at ``side``, empty, locked."""
    if isinstance(side, Path):
        _not_there(side)
        with _file_locked(side):
            db = Database(side, keep_copy=False)
            try:
                yield db
            finally:
                db.close()
        return
    with _server(side) as place:
        if place.tables():
            raise MoveError(
                f"the schema {side.schema_name} holds tables: a move goes into"
                f" an empty schema only. How to set the old one aside: {SET_ASIDE}"
            )
        yield Database(place=place)


def _not_there(path: Path) -> None:
    if path.exists():
        raise MoveError(
            f"{path} exists: a move goes into a new database only."
            " Move the file aside first"
        )


def _current(schema: int) -> None:
    if schema < SCHEMA_VERSION:
        raise MoveError(
            f"the database has schema {schema}, this version {SCHEMA_VERSION}:"
            " start the service on it once, then move"
        )
    if schema > SCHEMA_VERSION:
        raise MoveError(
            f"the database has schema {schema}, this version supports up to"
            f" {SCHEMA_VERSION}: update the service first"
        )


@contextmanager
def _file_locked(path: Path) -> Iterator[None]:
    """The lock a running service holds beside its file."""
    try:
        with locks.exclusive_lock(service_lock(path)):
            yield
    except locks.LockedError:
        raise _running() from None


@contextmanager
def _server(side: Server) -> Iterator[ServerPlace]:
    """The schema of ``side``, connected alone, with the lock a running
    service holds on it. A database opened on it closes with it."""
    with ExitStack() as held:
        place = ServerPlace(side)
        held.callback(place.close)
        place.open(SCHEMA_VERSION, SCHEMA_VERSION)
        try:
            held.enter_context(place.claimed())
        except StorageInUseError:
            raise _running() from None
        yield place


def _running() -> MoveError:
    return MoveError("the service is running on this database: stop it first")


def _sums(records: Records) -> dict[str, _Sum]:
    """Per table its rows and the SHA-256 of their lines, in the order of
    the key. The mark of a move is no record."""
    sums: dict[str, _Sum] = {}
    for table in records.tables():
        digest = hashlib.sha256()
        count = 0
        key = table.columns.index("key") if table.name == "meta" else None
        for row in records.rows(table.name):
            if key is not None and row[key] == MOVING:
                continue
            digest.update(row_line(row))
            count += 1
        sums[table.name] = _Sum(count, digest.hexdigest())
    return sums


def _moved(sums: dict[str, _Sum]) -> Moved:
    return Moved(len(sums), sum(s.rows for s in sums.values()))
