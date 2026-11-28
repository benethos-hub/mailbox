"""A database of a program on a file, through the storage alone, on the
small program of ``revision_helpers``: made by its revisions, opened
again, refused when its two numbers disagree, exported and read back,
checked and moved into another file, and locked while a program runs."""

from __future__ import annotations

import io
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from benethos_mailbox_common.storage import locks, sqlite_file, stores
from benethos_mailbox_common.storage.database import Database
from benethos_mailbox_common.storage.errors import StorageError, StorageInUseError
from benethos_mailbox_common.storage.export import export_records, import_records
from benethos_mailbox_common.storage.move import MoveError, check_move, move_records
from benethos_mailbox_common.storage.shape import Shape

from .revision_helpers import first_in, program


@pytest.fixture
def shape(tmp_path: Path) -> Shape:
    return program(first_in(tmp_path / "versions", items=False))


def _filled(shape: Shape, path: Path) -> Path:
    """A database of ``shape`` at ``path`` with five items."""
    Database(shape, path).close()
    with closing(sqlite3.connect(path)) as raw, raw:
        raw.executemany(
            "INSERT INTO items (id, name) VALUES (?, ?)",
            [(f"i{n}", f"Name {n}") for n in range(5)],
        )
    return path


def _exported(db: Database) -> bytes:
    out = io.BytesIO()
    with db.view() as records:
        export_records(records, out)
    return out.getvalue()


def test_a_new_database_is_made_by_its_revisions_and_opened_again(
    shape: Shape, tmp_path: Path
) -> None:
    path = tmp_path / "program.db"
    db = Database(shape, path)
    assert db.migrated is not None
    assert (db.migrated.before, db.migrated.after) == (0, 26)
    assert db.schema_version() == 26
    assert list(db.rows("items")) == []
    db.close()

    again = Database(shape, path)
    assert again.migrated is None
    again.close()


def test_a_database_whose_two_numbers_disagree_is_refused(
    shape: Shape, tmp_path: Path
) -> None:
    path = tmp_path / "torn.db"
    Database(shape, path).close()
    with closing(sqlite3.connect(path)) as raw, raw:
        raw.execute("UPDATE alembic_version SET version_num = '0025'")

    with pytest.raises(StorageError, match="says schema 26 and its revisions 25"):
        Database(shape, path)


def test_an_export_is_read_back_table_for_table(shape: Shape, tmp_path: Path) -> None:
    source = Database(shape, _filled(shape, tmp_path / "source.db"))
    data = _exported(source)
    target = Database(shape)
    try:
        counts = import_records(io.BytesIO(data), target, shape.noun)
        assert counts == {"items": 5, "meta": 1}
        assert list(target.rows("items")) == list(source.rows("items"))
        assert _exported(target) == data
    finally:
        source.close()
        target.close()


def test_a_move_copies_every_record_into_another_file(
    shape: Shape, tmp_path: Path
) -> None:
    source = _filled(shape, tmp_path / "source.db")

    assert check_move(shape, source).tables == 2
    moved = move_records(shape, source, tmp_path / "target.db")

    assert moved.rows == check_move(shape, source).rows
    target = Database(shape, tmp_path / "target.db")
    assert len(list(target.rows("items"))) == 5
    target.close()


def test_a_value_that_does_not_fit_its_column_stops_the_move(
    shape: Shape, tmp_path: Path
) -> None:
    source = _filled(shape, tmp_path / "source.db")
    with closing(sqlite3.connect(source)) as raw, raw:
        raw.execute("UPDATE items SET name = X'00ff' WHERE id = 'i0'")

    with pytest.raises(MoveError, match="items.name: 1"):
        check_move(shape, source)
    assert not (tmp_path / "target.db").exists()


def test_a_running_program_holds_its_file_from_a_tool(
    shape: Shape, tmp_path: Path
) -> None:
    path = tmp_path / "program.db"
    Database(shape, path).close()

    with locks.exclusive_lock(sqlite_file.lock_file(path)):
        with pytest.raises(StorageInUseError, match="test program is running"):
            with stores.file_claimed(shape, path):
                pass
    with stores.file_claimed(shape, path):
        pass
