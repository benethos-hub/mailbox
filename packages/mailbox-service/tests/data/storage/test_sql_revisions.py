"""The revisions of the service: they go on where its old steps end,
each writes its number, a database the old steps made is kept, and
none released is changed. How a revision runs is held by the tests of
mailbox-common (``tests/storage/test_revisions.py``)."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_common.storage import revision
from benethos_mailbox_common.storage.file_place import sqlite_engine
from benethos_mailbox_common.storage.revisions import Revisions
from benethos_mailbox_service.data.storage import Database
from benethos_mailbox_service.data.storage.sql import revisions
from benethos_mailbox_service.data.storage.sqlite.migrations import MIGRATIONS
from benethos_mailbox_service.errors import StorageError

from ...schema_helpers import at_schema, run, select, value


@pytest.fixture
def conn() -> Iterator[sa.Connection]:
    driver = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    engine = sqlite_engine(lambda: driver)
    with engine.connect() as connection:
        yield connection
    engine.dispose()
    driver.close()


def test_the_revisions_go_on_where_the_old_steps_end() -> None:
    numbers = revisions.REVISIONS.numbers()
    assert numbers[0] == revisions.BASELINE == MIGRATIONS.schema_version
    assert numbers == list(range(numbers[0], numbers[-1] + 1))
    assert numbers[-1] == revisions.SCHEMA_VERSION


def test_every_revision_writes_its_number_into_meta(conn: sa.Connection) -> None:
    for number in revisions.REVISIONS.numbers():
        revisions.REVISIONS.upgrade(conn, number)
        assert Revisions.mark(conn) == number
        with conn.begin():
            held = conn.exec_driver_sql(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).scalar()
        assert held == str(number)


def test_a_database_the_old_steps_made_is_marked_and_kept(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    raw = at_schema(path, revisions.BASELINE)
    raw.execute(
        "INSERT INTO roles (id, grants, service, position) VALUES ('r', '[]', '[]', 1)"
    )
    raw.close()
    db = Database(path)
    # The file is rewritten once to shrink: the schema stays.
    assert db.migrated is not None
    assert (db.migrated.before, db.migrated.after) == (26, 26)
    assert value(db, "SELECT version_num FROM alembic_version") == "0026"
    assert [r[0] for r in select(db, "SELECT id FROM roles")] == ["r"]
    db.close()
    again = Database(path)
    assert again.migrated is None
    assert [r[0] for r in select(again, "SELECT id FROM roles")] == ["r"]
    again.close()


def test_a_new_database_is_made_by_the_revisions(tmp_path: Path) -> None:
    db = Database(tmp_path / "new.db")
    assert db.migrated is not None
    assert (db.migrated.before, db.migrated.after) == (0, revisions.SCHEMA_VERSION)
    assert db.schema_version() == revisions.SCHEMA_VERSION
    db.close()


def test_a_database_whose_two_numbers_disagree_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "torn.db"
    db = Database(path)
    run(db, "UPDATE alembic_version SET version_num = '0025'")
    db.close()
    with pytest.raises(StorageError, match="says schema 26 and its revisions 25"):
        Database(path)


# What each revision of a release runs, as a hash of its module: a
# database of that release has run it, so it is never changed. A release
# adds its own. None so far. The base in revision.py is not part of it:
# a change there that changes what a released step does is a new
# revision, never an edit.
RELEASED_REVISIONS: dict[int, str] = {}


def _module(number: int) -> Path:
    [path] = revisions.VERSIONS.glob(f"r{number:04d}_*.py")
    return path


def fingerprint(number: int) -> str:
    return hashlib.sha256(
        _module(number).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()


def test_a_released_revision_is_never_changed() -> None:
    changed = [
        number
        for number, digest in sorted(RELEASED_REVISIONS.items())
        if fingerprint(number) != digest
    ]
    assert changed == [], "shipped in a release: make a new revision instead"


def test_every_revision_is_a_class_named_after_its_number() -> None:
    for number in revisions.REVISIONS.numbers():
        path = _module(number)
        assert re.fullmatch(rf"r{number:04d}_\w+\.py", path.name), path.name
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        [step] = [
            v
            for v in vars(module).values()
            if isinstance(v, type)
            and issubclass(v, revisions.Revision)
            and v is not revisions.Revision
        ]
        assert step.version == number, path.name
        assert step.__name__.startswith(f"R{number:04d}"), path.name
        assert module.revision == revision.name_of(number), path.name
