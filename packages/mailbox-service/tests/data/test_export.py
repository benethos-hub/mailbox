"""The logical export: a database written as lines and read back into
a new one, the same table for table, and every export that does not fit
refused."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.data.export import ExportError, read_export, write_export
from benethos_mailbox_service.data.models import ChangeRecord
from benethos_mailbox_service.data.storage import Database, repositories_on

from ..schema_helpers import SEED, at_schema, exported, run

# The export of that seed at schema 26, written once by the version
# before the export read its tables from the definitions, and never
# changed: every table holds rows.
EXPORTED = Path(__file__).parent / "exports" / "schema_26.jsonl"
MARK = "a-value-never-in-a-message"


@pytest.fixture
def source(tmp_path: Path) -> Database:
    """A database with every table filled: the seed of schema 25,
    migrated."""
    raw = at_schema(tmp_path / "source.db", 25)
    raw.executescript(SEED.read_text(encoding="utf-8"))
    raw.execute(
        "INSERT INTO roles (id, grants) VALUES (?, '[]')", (f"two\nlines {MARK}",)
    )
    raw.close()
    return Database(tmp_path / "source.db")


def test_an_export_is_read_back_table_for_table(source: Database) -> None:
    data = exported(source)
    target = Database()
    counts = read_export(io.BytesIO(data), target)
    assert counts == {t.name: len(list(source.rows(t.name))) for t in source.tables()}
    for table in source.tables():
        assert list(target.rows(table.name)) == list(source.rows(table.name)), table
    assert exported(target) == data
    source.close()
    target.close()


def _by_table(data: bytes) -> dict[str, list[object]]:
    tables: dict[str, list[object]] = {}
    rows: list[object] = []
    for line in data.splitlines():
        value = json.loads(line)
        if isinstance(value, dict) and "table" in value:
            rows = tables.setdefault(value["table"], [value["columns"]])
        elif isinstance(value, list):
            rows.append(value)
    return tables


def test_an_export_of_the_version_before_is_read_back() -> None:
    data = EXPORTED.read_bytes()
    target = Database()
    counts = read_export(io.BytesIO(data), target)
    assert all(counts.values()), "a table left empty"
    written = _by_table(data)
    again = _by_table(exported(target))
    assert again.keys() == written.keys()
    for table, rows in written.items():
        assert again[table] == rows, table
    target.close()


def _lines(data: bytes) -> list[object]:
    return [json.loads(line) for line in data.splitlines()]


def _joined(lines: list[object]) -> io.BytesIO:
    return io.BytesIO(b"".join(json.dumps(v).encode() + b"\n" for v in lines))


def _refused(lines: list[object], message: str) -> None:
    target = Database()
    with pytest.raises(ExportError, match=message) as refused:
        read_export(_joined(lines), target)
    target.close()
    assert MARK not in str(refused.value)


def test_what_does_not_fit_is_refused(source: Database) -> None:
    lines = _lines(exported(source))
    roles = lines.index(
        {"table": "roles", "columns": ["id", "grants", "service", "position"]}
    )
    _refused([{"export": 1, "schema": 7}, *lines[1:]], "has schema 7")
    _refused([{"no": "export"}, *lines[1:]], "not an export")
    _refused(
        [*lines[:roles], {"table": "nope", "columns": ["id"]}, *lines[roles + 1 :]],
        "table nope is not one of the schema",
    )
    _refused(
        [
            *lines[:roles],
            {"table": "roles", "columns": ["id", "secret"]},
            *lines[roles + 1 :],
        ],
        "columns of the table roles",
    )
    end = lines.index({"end": "roles", "rows": 3})
    _refused(
        [*lines[:end], {"end": "roles", "rows": 4}, *lines[end + 1 :]],
        "table roles does not hold the rows it names",
    )
    _refused(
        [*lines[: roles + 1], ["short"], *lines[roles + 2 :]], "row of the table roles"
    )
    _refused(lines[:-1], "ends early")
    _refused([*lines[:-1], {"tables": 1}], "does not name every table")
    source.close()


def test_an_export_cut_in_a_line_is_refused(source: Database) -> None:
    data = exported(source)
    target = Database()
    with pytest.raises(ExportError, match="ends early"):
        read_export(io.BytesIO(data[: len(data) // 2]), target)
    target.close()
    source.close()


def test_a_purged_feed_counts_on_after_an_export(source: Database) -> None:
    record = ChangeRecord(
        type="message.created",
        id="msg_1",
        account_id="acc_seed2",
        at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    feed = repositories_on(source).changes
    feed.append([record, record])
    run(source, "DELETE FROM changes WHERE seq > 7")
    target = Database()
    read_export(io.BytesIO(exported(source)), target)
    repositories_on(target).changes.append([record])
    assert [row[0] for row in target.rows("changes")] == [5, 7, 12]
    source.close()
    target.close()


def test_an_export_of_a_view_is_the_one_of_the_database(source: Database) -> None:
    """A view holds the records of one moment: what is written while it
    is open is not in it, and its export is byte for byte the one of the
    database at that moment."""
    before = exported(source)
    with source.view() as records:
        repositories_on(source).changes.append(
            [
                ChangeRecord(
                    type="message.created",
                    id="msg_written_meanwhile",
                    account_id="acc_seed1",
                    at=datetime(2026, 11, 26, tzinfo=UTC),
                )
            ]
        )
        out = io.BytesIO()
        write_export(records, out)
    assert out.getvalue() == before
    assert exported(source) != before
    source.close()
