"""The records of a store as a stream of lines, and back: the logical
export, the ground of backup format 3, independent of the file of a
database.

One JSON value per line, in UTF-8:

- the head: ``{"export": 1, "schema": <version>}``
- per table, in the order of its references: ``{"table": <name>,
  "columns": [...]}``, a list of values per row, and
  ``{"end": <name>, "rows": <count>}``
- the last line: ``{"tables": <count>}``

A BLOB is ``{"b": "<Base64>"}``, every other value its JSON value. A
message names a table, never a value.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Sequence
from typing import IO, Any

from .storage import Records, Store

FORMAT = 1


class ExportError(Exception):
    """An export that cannot be read into the store: what is wrong, never
    a value of it."""


def write_export(store: Records, out: IO[bytes]) -> dict[str, int]:
    """Every record of ``store`` to ``out``. The rows of each table."""
    counts: dict[str, int] = {}
    _line(out, {"export": FORMAT, "schema": store.schema_version()})
    for table in store.tables():
        _line(out, {"table": table.name, "columns": list(table.columns)})
        count = 0
        for row in store.rows(table.name):
            out.write(row_line(row))
            count += 1
        _line(out, {"end": table.name, "rows": count})
        counts[table.name] = count
    _line(out, {"tables": len(counts)})
    return counts


def read_export(source: IO[bytes], store: Store) -> dict[str, int]:
    """The export in ``source`` into ``store``, whose tables hold nothing
    yet and whose schema is the export's. The rows of each table.
    ExportError when the export does not fit or ends early."""
    lines = _Lines(source)
    head = lines.next()
    if not isinstance(head, dict) or head.get("export") != FORMAT:
        raise ExportError("not an export of this service")
    if head.get("schema") != store.schema_version():
        raise ExportError(
            f"the export has schema {head.get('schema')},"
            f" the database {store.schema_version()}"
        )
    known = {table.name: table for table in store.tables()}
    counts: dict[str, int] = {}
    while True:
        line = lines.next()
        if not isinstance(line, dict):
            raise ExportError("a row stands outside a table")
        if "tables" in line:
            if line["tables"] != len(counts):
                raise ExportError("the export does not name every table it holds")
            return counts
        name = line.get("table")
        columns = line.get("columns")
        if name not in known or name in counts:
            raise ExportError(f"the table {name} is not one of the schema")
        if not isinstance(columns, list) or not set(columns) <= set(
            known[name].columns
        ):
            raise ExportError(f"the columns of the table {name} are not the schema's")
        rows = _Rows(lines, name, len(columns))
        store.fill(name, columns, rows)
        if rows.count != rows.said:
            raise ExportError(f"the table {name} does not hold the rows it names")
        counts[name] = rows.count


class _Lines:
    """The values of ``source``, one per line. A last line without its
    line end is an export that ended early."""

    def __init__(self, source: IO[bytes]) -> None:
        self._source = source

    def next(self) -> Any:
        raw = self._source.readline()
        if not raw.endswith(b"\n"):
            raise ExportError("the export ends early")
        try:
            return json.loads(raw)
        except ValueError:
            raise ExportError("a line of the export is not JSON") from None


class _Rows:
    """The rows of one table, up to its end line, with the count it says."""

    def __init__(self, lines: _Lines, table: str, width: int) -> None:
        self._lines = lines
        self._table = table
        self._width = width
        self.count = 0
        self.said: int | None = None

    def __iter__(self) -> Iterator[list[Any]]:
        while True:
            line = self._lines.next()
            if isinstance(line, dict):
                if line.get("end") != self._table:
                    raise ExportError(f"the table {self._table} has no end")
                self.said = line.get("rows")
                return
            if not isinstance(line, list) or len(line) != self._width:
                raise ExportError(f"a row of the table {self._table} does not fit")
            self.count += 1
            yield [_stored(v, self._table) for v in line]


def row_line(row: Sequence[Any]) -> bytes:
    """A row as its line of the export."""
    return _encoded([_value(v) for v in row])


def _line(out: IO[bytes], value: object) -> None:
    out.write(_encoded(value))


def _encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _value(value: object) -> object:
    if isinstance(value, bytes):
        return {"b": base64.b64encode(value).decode("ascii")}
    return value


def _stored(value: Any, table: str) -> Any:
    if isinstance(value, dict):
        try:
            return base64.b64decode(value["b"], validate=True)
        except (KeyError, TypeError, ValueError):
            raise ExportError(f"a value of the table {table} is not one") from None
    if isinstance(value, list):
        raise ExportError(f"a value of the table {table} is not one")
    return value
