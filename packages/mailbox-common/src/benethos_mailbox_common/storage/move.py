"""The move of the records from one database to another, the file of
SQLite to a schema on PostgreSQL or back (``storage move``).

Before anything is written, every value of the source is held to the
kind of its column: SQLite keeps a text in a column of numbers or of
bytes, and the character NUL in a text, which PostgreSQL refuses or
takes as something else. A value that
does not fit stops the move. The message names the table, the column and
how many, never a value.

The target must be empty: a file that is not there yet, or a schema
without tables. Both sides are locked as a running program locks them,
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

from . import sqlite_file
from .clock import iso, utc_now
from .errors import SchemaNotEmptyError, StorageInUseError
from .export import row_line
from .server_place import Server
from .shape import Shape
from .stored import Records, Store
from .stores import Claim, claimed, file_claimed, file_store

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
                if value is not None and not _fits(value, fits[index]):
                    counts[index] += 1
        found += [
            Misfit(table.name, column, count)
            for column, count in zip(table.columns, counts, strict=True)
            if count
        ]
    return found


def _fits(value: object, kind: type) -> bool:
    """Whether ``value`` fits a column of ``kind``. A text that holds the
    character NUL does not: SQLite keeps it, PostgreSQL refuses it."""
    if not isinstance(value, kind):
        return False
    return not (isinstance(value, str) and "\x00" in value)


def misfit_error(found: list[Misfit]) -> MoveError:
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


def check_move(shape: Shape, source: Path | Server) -> Moved:
    """Hold every value of the database of ``shape`` at ``source`` to its
    column, writing nothing. MoveError names what does not fit."""
    with _move_source(shape, source) as db, db.view() as records:
        found = misfits(records)
        if found:
            raise misfit_error(found)
        sums = _sums(records)
    return _moved(sums)


def move_records(shape: Shape, source: Path | Server, target: Path | Server) -> Moved:
    """Every record of the database of ``shape`` at ``source`` into
    ``target``, which holds none yet, checked first and compared after.
    MoveError when it cannot be made or did not hold: then the target
    keeps the mark and is not opened."""
    if isinstance(target, Path):
        _target_free(target)
    with ExitStack() as held:
        db = held.enter_context(_move_source(shape, source))
        records = held.enter_context(db.view())
        found = misfits(records)
        if found:
            raise misfit_error(found)
        made = held.enter_context(_target_of_move(shape, target))
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
def _move_source(shape: Shape, side: Path | Server) -> Iterator[Store]:
    """The database at ``side``, at this version's schema, locked."""
    if isinstance(side, Path):
        if not side.exists():
            raise MoveError(f"there is no database at {side}")
        try:
            _at_this_version(shape, sqlite_file.inspect_file(side, shape.noun))
        except ValueError as exc:
            raise MoveError(f"the database at {side} is unsound: {exc}") from None
        with _file_locked(shape, side):
            db = file_store(shape, side, keep_copy=False)
            try:
                yield db
            finally:
                db.close()
        return
    with _claimed_server(shape, side) as claim:
        if not claim.tables():
            raise MoveError(f"the schema {side.schema_name} holds no database")
        _at_this_version(shape, claim.held_schema())
        yield claim.store()


@contextmanager
def _target_of_move(shape: Shape, side: Path | Server) -> Iterator[Store]:
    """A new database at ``side``, empty, locked."""
    if isinstance(side, Path):
        _target_free(side)
        with _file_locked(shape, side):
            db = file_store(shape, side, keep_copy=False)
            try:
                yield db
            finally:
                db.close()
        return
    with _claimed_server(shape, side, empty="a move") as claim:
        yield claim.store()


def _target_free(path: Path) -> None:
    if path.exists():
        raise MoveError(
            f"{path} exists: a move goes into a new database only."
            " Move the file aside first"
        )


def _at_this_version(shape: Shape, schema: int) -> None:
    newest, noun = shape.newest, shape.noun
    if schema < newest:
        raise MoveError(
            f"the database has schema {schema}, this version {newest}:"
            f" start the {noun} on it once, then move"
        )
    if schema > newest:
        raise MoveError(
            f"the database has schema {schema}, this version supports up to"
            f" {newest}: update the {noun} first"
        )


@contextmanager
def _file_locked(shape: Shape, path: Path) -> Iterator[None]:
    """The lock a running program holds beside its file."""
    with ExitStack() as held:
        try:
            held.enter_context(file_claimed(shape, path))
        except StorageInUseError:
            raise _move_running(shape) from None
        yield


@contextmanager
def _claimed_server(
    shape: Shape, side: Server, *, empty: str | None = None
) -> Iterator[Claim]:
    """The schema of ``side``, connected alone, with the lock a running
    program holds on it, empty when ``empty`` names what goes into it. A
    database opened on it closes with it."""
    with ExitStack() as held:
        try:
            claim = held.enter_context(claimed(shape, side, empty=empty))
        except StorageInUseError:
            raise _move_running(shape) from None
        except SchemaNotEmptyError as exc:
            raise MoveError(str(exc)) from None
        yield claim


def _move_running(shape: Shape) -> MoveError:
    return MoveError(f"the {shape.noun} is running on this database: stop it first")


def _sums(records: Records) -> dict[str, _Sum]:
    """Per table its rows and the SHA-256 of their lines, in the order of
    the key. The mark of a move is no record, and no row of it."""
    sums: dict[str, _Sum] = {}
    for table in records.tables():
        digest = hashlib.sha256()
        count = 0
        for row in records.rows(table.name):
            digest.update(row_line(row))
            count += 1
        sums[table.name] = _Sum(count, digest.hexdigest())
    return sums


def _moved(sums: dict[str, _Sum]) -> Moved:
    return Moved(len(sums), sum(s.rows for s in sums.values()))
