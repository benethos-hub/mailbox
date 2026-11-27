"""The state file: migrations, the tables, and a reader beside the writer."""

from __future__ import annotations

import inspect
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_agents.errors import ConfigError, StateFileError
from benethos_mailbox_agents.records import (
    KEYWORD_REMOVED,
    MESSAGE_GONE,
    MessageRef,
    StepResult,
)
from benethos_mailbox_agents.store import (
    MIGRATIONS,
    SCHEMA_VERSION,
    Store,
    path_for,
)
from benethos_mailbox_agents.store import store as store_module

from ..agents_helpers import DOCS

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
REF = MessageRef(account_id="acc", message_id="m1")
OTHER = MessageRef(account_id="acc", message_id="m2")


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return path_for(tmp_path / "data", "invoices")


@pytest.fixture
def store(path: Path) -> Iterator[Store]:
    with Store.open(path) as opened:
        yield opened


def test_the_file_is_named_after_the_agent(tmp_path: Path) -> None:
    assert path_for(tmp_path, "invoices").name == "invoices.db"


def _read(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


def test_a_new_file_runs_every_migration_in_wal_mode(path: Path, store: Store) -> None:
    assert store.version == SCHEMA_VERSION
    assert _read(path, "PRAGMA journal_mode") == [("wal",)]


def test_opening_again_runs_nothing_twice(path: Path, store: Store) -> None:
    store.set_cursor("s1", NOW)
    store.close()
    with Store.open(path) as again:
        assert (again.migrated, again.version) == (None, SCHEMA_VERSION)
        assert again.cursor() == "s1"


def test_one_writer_per_state_file(path: Path, store: Store) -> None:
    with pytest.raises(ConfigError, match="already running: one writer"):
        Store.open(path)
    with Store.open(path, read_only=True) as reader:
        assert reader.cursor() is None

    store.close()
    with Store.open(path) as again:
        again.set_cursor("s2", NOW)


def test_the_tables_are_those_of_the_state_spec(path: Path, store: Store) -> None:
    section = (DOCS / "concept" / "state.md").read_text(encoding="utf-8")
    named = set(re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.MULTILINE))
    tables = {
        row[0]
        for row in _read(
            path,
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'",
        )
    }

    assert named == tables


def test_a_reader_needs_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no state file"):
        Store.open(tmp_path / "none.db", read_only=True)


def test_a_data_folder_that_is_a_file_is_a_state_file_error(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("not a folder", encoding="utf-8")

    with pytest.raises(StateFileError) as raised:
        Store.open(path_for(tmp_path / "data", "invoices"))

    assert raised.value.message == (
        "the state file invoices.db: its folder or lock cannot be made "
        "(FileExistsError)"
    )


def test_a_lock_that_cannot_be_made_is_a_state_file_error(tmp_path: Path) -> None:
    (tmp_path / "invoices.db.lock").mkdir()

    with pytest.raises(StateFileError, match="its folder or lock cannot be made"):
        Store.open(path_for(tmp_path, "invoices"))


def test_a_reader_refuses_a_newer_schema(path: Path, store: Store) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(SCHEMA_VERSION + 1),),
        )

    with pytest.raises(ConfigError, match="schema version"):
        Store.open(path, read_only=True)


def test_a_reader_refuses_an_older_schema(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with closing(sqlite3.connect(path)) as raw, raw:
        for statement in MIGRATIONS.step(1).statements:
            raw.execute(inspect.cleandoc(statement))
        raw.execute("PRAGMA user_version = 1")

    with pytest.raises(ConfigError, match="start the agent once"):
        Store.open(path, read_only=True)


def test_a_reader_sees_the_writer_and_cannot_write(path: Path, store: Store) -> None:
    store.set_cursor("s2", NOW)

    with Store.open(path, read_only=True) as reader:
        assert reader.cursor() == "s2"
        with pytest.raises(StateFileError, match="readonly"):
            reader.set_cursor("s3", NOW)


def test_another_process_reads_while_the_writer_holds_the_file(
    path: Path, store: Store
) -> None:
    store.enqueue(REF, NOW)
    script = (
        "import sqlite3,sys;"
        "c=sqlite3.connect(sys.argv[1]+'?mode=ro',uri=True);"
        "print(c.execute('SELECT COUNT(*) FROM messages').fetchone()[0]);"
        "c.close()"
    )

    found = subprocess.run(
        [sys.executable, "-c", script, path.resolve().as_uri()],
        capture_output=True,
        text=True,
        check=True,
    )

    assert found.stdout.strip() == "1"


def test_a_message_is_enqueued_once(store: Store) -> None:
    assert store.enqueue(REF, NOW)
    assert not store.enqueue(REF, NOW + timedelta(minutes=1))

    row = store.message(REF)
    assert row is not None
    assert (row.state, row.attempts, row.created) == ("pending", 0, NOW)


def test_again_makes_a_finished_message_pending_anew(store: Store) -> None:
    store.enqueue(REF, NOW)
    store.set_state(REF, "done", NOW, attempts=2)

    assert store.enqueue(REF, NOW, again=True)
    row = store.message(REF)
    assert row is not None
    assert (row.state, row.attempts) == ("pending", 0)
    assert not store.enqueue(REF, NOW, again=True)


def test_due_waits_for_the_next_attempt(store: Store) -> None:
    store.enqueue(REF, NOW)
    store.enqueue(OTHER, NOW + timedelta(seconds=1))
    store.set_state(
        REF, "pending", NOW, attempts=1, next_attempt=NOW + timedelta(hours=1)
    )

    assert [row.ref for row in store.due(NOW + timedelta(minutes=1), 50)] == [OTHER]
    assert len(store.due(NOW + timedelta(hours=2), 50)) == 2


def test_counts_name_every_state(store: Store) -> None:
    store.enqueue(REF, NOW)
    store.enqueue(OTHER, NOW)
    store.set_state(OTHER, "skipped", NOW)

    assert store.counts() == {
        "pending": 1,
        "skipped": 1,
        "decided": 0,
        "done": 0,
        "failed": 0,
    }
    assert store.oldest_pending() == NOW
    assert [row.ref for row in store.messages("skipped")] == [OTHER]
    assert len(store.messages()) == 2
    assert len(store.messages(limit=1)) == 1
    assert [row.ref for row in store.messages("skipped", 5)] == [OTHER]


def test_an_unknown_state_is_refused(store: Store) -> None:
    with pytest.raises(ValueError, match="no message state"):
        store.set_state(REF, "lost", NOW)


def test_a_naive_time_is_refused(store: Store) -> None:
    with pytest.raises(ValueError, match="zone"):
        store.set_cursor("s", datetime(2026, 1, 1))


def test_a_step_is_found_by_prompt_version_and_model(store: Store) -> None:
    step = StepResult(
        step="model",
        prompt_version="v1",
        model="reported-model",
        result={"label": "invoice"},
        tokens_in=10,
        tokens_out=2,
        duration_ms=5,
        at=NOW,
    )
    store.add_step(REF, step, "alias")

    assert store.step(REF, "model", "v1", "alias") == step
    assert store.step(REF, "model", "v2", "alias") is None
    assert store.step(REF, "model", "v1", "other") is None
    assert store.steps(REF) == [step]
    assert store.model_calls_since(NOW) == 1
    assert store.model_calls_since(NOW + timedelta(seconds=1)) == 0


def test_an_action_keeps_what_was_before(store: Store) -> None:
    store.add_action(
        REF,
        action="move_to_folder",
        argument="f2",
        before={"folders": ["f1"]},
        stage="full",
        executed=True,
        now=NOW,
    )

    (row,) = store.actions(REF)
    assert (row.argument, row.before, row.executed) == ("f2", {"folders": ["f1"]}, True)
    assert store.actions() == [row]
    assert store.actions(OTHER) == []


def test_an_open_item_from_opening_to_closing(store: Store) -> None:
    due = NOW + timedelta(days=3)
    store.open_item(REF, "t1", due, NOW)

    assert store.due_items(NOW) == []
    (item,) = store.due_items(due)
    assert (item.thread_id, item.is_open, item.keyword_set) == ("t1", True, False)
    assert store.items_in_thread("acc", "t1") == [item]

    store.mark_keyword(REF, True)
    assert store.due_items(due) == []
    assert store.close_item(REF, "replied", due)
    assert not store.close_item(REF, "replied", due)
    closed = store.item(REF)
    assert closed is not None
    assert (closed.is_open, closed.reason) == (False, "replied")
    assert store.items_in_thread("acc", "t1") == []


def test_opening_an_item_again_leaves_it_as_it_is(store: Store) -> None:
    store.open_item(REF, "t1", NOW, NOW)
    store.mark_keyword(REF, True)
    store.close_item(REF, "replied", NOW)

    store.open_item(REF, "t1", NOW + timedelta(days=5), NOW)

    item = store.item(REF)
    assert item is not None
    assert (item.is_open, item.reason) == (False, "replied")


def test_restarting_an_item_gives_it_a_new_deadline(store: Store) -> None:
    later = NOW + timedelta(days=5)
    store.open_item(REF, "t1", NOW, NOW)
    store.mark_keyword(REF, True)
    store.close_item(REF, "replied", NOW)

    store.restart_item(REF, later, NOW)

    item = store.item(REF)
    assert item is not None
    assert (item.is_open, item.keyword_set, item.due) == (True, False, later)


def test_an_item_a_person_closed_is_not_restarted(store: Store) -> None:
    store.open_item(REF, "t1", NOW, NOW)
    store.close_item(REF, "keyword_removed", NOW)

    store.restart_item(REF, NOW + timedelta(days=5), NOW)

    item = store.item(REF)
    assert item is not None
    assert (item.is_open, item.reason) == (False, "keyword_removed")


def test_the_store_spells_no_reason_an_item_closed_for() -> None:
    """Why an item closed is the records' to name: the state file only
    stores it, and reads the one that matters through KEYWORD_REMOVED."""
    source = inspect.getsource(store_module)

    assert KEYWORD_REMOVED not in source
    assert MESSAGE_GONE not in source


def test_kept_calls_are_purged(store: Store) -> None:
    store.add_call(REF, {"messages": []}, {"choices": []}, NOW)
    store.add_call(REF, {}, {}, NOW + timedelta(days=2))

    assert store.purge_calls(NOW + timedelta(days=1)) == 1
    assert store.count_calls() == 1


def test_a_purged_call_leaves_no_text_in_the_files(path: Path) -> None:
    marker = "Marker-of-a-kept-call-7f3a"
    with Store.open(path) as store:
        store.add_call(REF, {"messages": [{"content": marker}]}, {}, NOW)
        assert store.purge_calls(NOW + timedelta(days=1)) == 1

    # Read only after the store is closed: Windows keeps an open file locked.
    files = [path, *(path.with_name(path.name + end) for end in ("-wal", "-shm"))]
    found = [f.name for f in files if f.exists() and marker.encode() in f.read_bytes()]
    assert found == []


def test_progress(store: Store) -> None:
    assert store.progress() is None
    store.set_progress(NOW)
    store.set_progress(NOW + timedelta(seconds=5))

    assert store.progress() == NOW + timedelta(seconds=5)


def test_a_text_that_is_not_utf_8_is_a_state_file_error(store: Store) -> None:
    lone = MessageRef(account_id="acc", message_id=f"m{chr(0xD800)}")

    with pytest.raises(StateFileError, match="not valid UTF-8"):
        store.enqueue(lone, NOW)


@pytest.mark.parametrize("read_only", [True, False])
def test_a_file_that_is_no_state_file_is_named(tmp_path: Path, read_only: bool) -> None:
    path = tmp_path / "counting.db"
    path.write_text("not a database, but long enough to be read as one\n" * 20)

    with pytest.raises(StateFileError, match="counting.db"):
        Store.open(path, read_only=read_only)
