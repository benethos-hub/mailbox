"""What the base of the revisions offers a step: the number into meta, a
check, a refusal, notes for the start, rows worked out in Python, a step
outside a transaction, a copy of the file before it. Each with a
revision of a folder of its own."""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_common.storage import database as stored_database
from benethos_mailbox_common.storage import revision
from benethos_mailbox_common.storage.file_place import sqlite_engine
from benethos_mailbox_common.storage.revisions import Revisions
from benethos_mailbox_service.data.storage import Database
from benethos_mailbox_service.data.storage.sql import revisions
from benethos_mailbox_service.data.storage.sql.database import SHAPE
from benethos_mailbox_service.errors import StorageError

from ...revision_helpers import second, steps_in

Steps = Callable[[str], Path]


@pytest.fixture
def steps_folder(tmp_path: Path) -> Steps:
    """A folder of revisions: the first, and a second of ``body``."""
    return lambda body: steps_in(tmp_path / "versions", body)


@pytest.fixture
def bare() -> Iterator[sa.Connection]:
    driver = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    engine = sqlite_engine(lambda: driver)
    with engine.connect() as connection:
        yield connection
    engine.dispose()
    driver.close()


def _held(conn: sa.Connection) -> str | None:
    with conn.begin():
        held: str | None = conn.exec_driver_sql(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).scalar()
    return held


def _rows(conn: sa.Connection, sql: str) -> list[tuple[object, ...]]:
    with conn.begin():
        return [tuple(r) for r in conn.exec_driver_sql(sql)]


def test_a_step_writes_its_number_into_meta(
    bare: sa.Connection, steps_folder: Steps
) -> None:
    folder = steps_folder("""
        def steps(self):
            op.add_column("items", sa.Column("seen", sa.Integer))
    """)
    Revisions(folder).upgrade(bare, 26)
    assert _held(bare) == "26"
    Revisions(folder).upgrade(bare, 27)
    assert _held(bare) == "27"
    assert Revisions.mark(bare) == 27


def test_rows_are_worked_out_in_python_in_chunks(
    bare: sa.Connection, steps_folder: Steps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(revision, "REWRITE_CHUNK", 2)
    folder = steps_folder("""
        def steps(self):
            done = self.rewrite("items", key=["id"], read=["name"],
                                write=["folded"],
                                change=lambda row: {"folded": row["name"].casefold()})
            self.note(f"{done} items folded")
    """)
    Revisions(folder).upgrade(bare, 26)
    notes = Revisions(folder).upgrade(bare, 27)
    assert notes == ["schema 27: 5 items folded"]
    assert _rows(bare, "SELECT id, folded FROM items ORDER BY id") == [
        (f"i{n}", f"name {n}") for n in range(5)
    ]


def test_a_change_must_give_the_columns_it_writes(
    bare: sa.Connection, steps_folder: Steps
) -> None:
    folder = steps_folder("""
        def steps(self):
            self.rewrite("items", key=["id"], read=["name"], write=["folded"],
                         change=lambda row: {"name": "x"})
    """)
    Revisions(folder).upgrade(bare, 26)
    with pytest.raises(StorageError, match="gave \\['name'\\], not \\['folded'\\]"):
        Revisions(folder).upgrade(bare, 27)
    assert Revisions.mark(bare) == 26
    assert _rows(bare, "SELECT DISTINCT name FROM items WHERE name = 'x'") == []


def test_a_failed_check_undoes_the_step(
    bare: sa.Connection, steps_folder: Steps
) -> None:
    folder = steps_folder("""
        def steps(self):
            self.conn.execute(sa.delete(ITEMS))

        def check(self):
            if not self.conn.execute(sa.select(ITEMS.c.id)).first():
                self.refuse("no item left")
    """)
    Revisions(folder).upgrade(bare, 26)
    with pytest.raises(StorageError, match="schema 27 cannot be reached: no item left"):
        Revisions(folder).upgrade(bare, 27)
    assert Revisions.mark(bare) == 26
    assert _held(bare) == "26"
    assert len(_rows(bare, "SELECT id FROM items")) == 5


def test_a_refused_step_leaves_nothing(
    bare: sa.Connection, steps_folder: Steps
) -> None:
    folder = steps_folder("""
        def steps(self):
            op.create_table("half", sa.Column("id", sa.Text, primary_key=True))
            self.refuse("the items do not fit")
    """)
    Revisions(folder).upgrade(bare, 26)
    with pytest.raises(StorageError, match="the items do not fit"):
        Revisions(folder).upgrade(bare, 27)
    assert Revisions.mark(bare) == 26
    assert "half" not in sa.inspect(bare).get_table_names()


def test_a_step_outside_a_transaction_stays_when_its_check_fails(
    bare: sa.Connection, steps_folder: Steps
) -> None:
    folder = steps_folder("""
        in_transaction = False

        def steps(self):
            op.create_index("items_name", "items", ["name"])

        def check(self):
            self.refuse("checked")
    """)
    Revisions(folder).upgrade(bare, 26)
    with pytest.raises(StorageError, match="checked"):
        Revisions(folder).upgrade(bare, 27)
    assert Revisions.mark(bare) == 26
    assert _held(bare) == "26"
    indexes = [i["name"] for i in sa.inspect(bare).get_indexes("items")]
    assert "items_name" in indexes


def test_a_step_that_asks_for_a_copy_gets_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "data" / "mailbox.db"
    Database(path).close()
    folder = tmp_path / "versions"
    folder.mkdir()
    for baseline in revisions.VERSIONS.glob("r0026_*.py"):
        shutil.copy(baseline, folder / baseline.name)
    (folder / "r0027_copied.py").write_text(
        second("""
            keeps_copy = True

            def steps(self):
                op.add_column("roles", sa.Column("note", sa.Text))
        """),
        encoding="utf-8",
    )
    shape = dataclasses.replace(SHAPE, versions=folder, newest=27)
    db = stored_database.Database(shape, path)
    assert db.migrated is not None
    assert (db.migrated.before, db.migrated.after) == (26, 27)
    [kept] = path.parent.glob("mailbox.db.before-schema-27-*")
    assert db.migrated.notes == (
        f"a copy of the database at schema 26 is kept: {kept.name}",
    )
    db.close()
    with sqlite3.connect(kept) as copy:
        [(held,)] = copy.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    copy.close()
    assert held == "26"
