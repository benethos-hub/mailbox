"""The steps of the state file: the old ones on sqlite3 up to schema 5,
each frozen once released, and a file of an earlier schema brought
forward with its rows."""

from __future__ import annotations

import inspect
import pkgutil
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_agents.errors import StateFileError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.store import (
    MIGRATIONS,
    SCHEMA_VERSION,
    Migrated,
    Store,
    path_for,
)
from benethos_mailbox_agents.store.migrations import (
    Migration,
    MigrationRegistry,
    versions,
)

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
REF = MessageRef(account_id="acc", message_id="m1")


def _read(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


class _Broken(Migration):
    version = 5
    statements = ("CREATE TABLE fine (x INTEGER)", "CREATE TABLE broken (")


def test_a_failed_step_leaves_the_file_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_agents.store import file

    path = tmp_path / "x.db"
    with closing(sqlite3.connect(path)) as raw, raw:
        for number in range(1, 5):
            for statement in MIGRATIONS.step(number).statements:
                raw.execute(inspect.cleandoc(statement))
        raw.execute("PRAGMA user_version = 4")
    steps = [MIGRATIONS.step(n) for n in range(1, 5)]
    monkeypatch.setattr(file, "MIGRATIONS", MigrationRegistry(*steps, _Broken()))
    with pytest.raises(StateFileError):
        Store.open(path)

    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 4
        tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master")}
    assert "fine" not in tables


# -- the migrations ----------------------------------------------------------------

# The fingerprint of each step that shipped in a release: a file of that
# release has run it, so it is never changed. A release adds its own. The
# fingerprint covers the step's whole module, comments included.
RELEASED: dict[int, str] = {
    # 0.1.0
    1: "7d0c1acff1d2e09ab1f24e0ff0f76f50c4b86e4210309a07e96b5ee945bc12ad",
    2: "c1bb1bdec56c2a961402d2453861d2cd6049d8f5196265df26207ce8a4a46409",
}


def test_a_released_migration_is_never_changed() -> None:
    for number, fingerprint in RELEASED.items():
        assert MIGRATIONS.step(number).fingerprint() == fingerprint, (
            f"migration {number} shipped in a release: make a new one instead"
        )


def test_each_migration_module_is_in_the_list_at_its_number() -> None:
    numbers = []
    for module in pkgutil.iter_modules(versions.__path__):
        found = re.fullmatch(r"v(\d{4})_\w+", module.name)
        assert found, f"{module.name} is not named vNNNN_<subject>"
        number = int(found.group(1))
        step = MIGRATIONS.step(number)
        assert type(step).__name__.startswith(f"V{number:04d}")
        assert type(step).__module__.endswith(f".{module.name}")
        numbers.append(number)

    assert sorted(numbers) == list(range(1, SCHEMA_VERSION + 1))


def test_each_migration_step_is_one_statement() -> None:
    for number in range(1, SCHEMA_VERSION + 1):
        for statement in MIGRATIONS.step(number).statements:
            text = inspect.cleandoc(statement)
            assert not sqlite3.complete_statement(text), text
            assert sqlite3.complete_statement(text + ";"), text


def test_the_registry_refuses_a_step_out_of_place() -> None:
    with pytest.raises(ValueError, match="stands at 1"):
        MigrationRegistry(_Broken())
    with pytest.raises(ValueError, match="no migration to schema 99"):
        MIGRATIONS.step(99)

    assert MIGRATIONS.pending(SCHEMA_VERSION) == ()


def test_opening_notes_what_was_migrated(tmp_path: Path) -> None:
    path = path_for(tmp_path / "data", "invoices")
    with Store.open(path) as new:
        assert new.migrated == Migrated(0, SCHEMA_VERSION)
    with Store.open(path) as current:
        assert current.migrated is None


def test_a_file_of_an_earlier_schema_is_brought_forward(tmp_path: Path) -> None:
    path = path_for(tmp_path / "data", "invoices")
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as raw, raw:
        for statement in MIGRATIONS.step(1).statements:
            raw.execute(inspect.cleandoc(statement))
        raw.execute("PRAGMA user_version = 1")

    with Store.open(path) as store:
        assert store.migrated is not None
        assert (store.migrated.before, store.migrated.after) == (1, SCHEMA_VERSION)
        columns = _read(path, "PRAGMA table_info(open_items)")
    assert "keyword_recorded_stage" in {row[1] for row in columns}


def test_the_former_word_of_the_middle_stage_is_written_as_suggest(
    tmp_path: Path,
) -> None:
    path = path_for(tmp_path / "data", "invoices")
    """A file of schema 2 names the middle stage keyword. After the
    migration it says suggest, so an action recorded only is not recorded
    again in suggest, and the keyword of an item is not tried again."""
    path.parent.mkdir(parents=True)
    at = NOW.isoformat()
    with closing(sqlite3.connect(path)) as raw, raw:
        for number in (1, 2):
            for statement in MIGRATIONS.step(number).statements:
                raw.execute(inspect.cleandoc(statement))
        raw.execute("PRAGMA user_version = 2")
        for stage in ("shadow", "keyword"):
            raw.execute(
                "INSERT INTO actions (account_id, message_id, action, argument, "
                "before, stage, executed, at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                ("acc", "m1", "add_keyword", "agent-x", "{}", stage, at),
            )
        raw.execute(
            "INSERT INTO open_items (account_id, message_id, opened, due, "
            "keyword_recorded_stage) VALUES ('acc', 'm1', ?, ?, 'keyword')",
            (at, at),
        )

    with Store.open(path) as store:
        assert store.migrated is not None
        assert (store.migrated.before, store.migrated.after) == (2, SCHEMA_VERSION)
        assert [row.stage for row in store.actions(REF)] == ["shadow", "suggest"]
        assert store.due_items(NOW + timedelta(days=1), "suggest") == []
        assert len(store.due_items(NOW + timedelta(days=1), "full")) == 1
