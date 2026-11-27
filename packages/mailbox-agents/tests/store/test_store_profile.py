"""The profile of the agent in its state file."""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from benethos_mailbox_agents.records import Profile
from benethos_mailbox_agents.store import MIGRATIONS, Store, path_for

PROFILE = Profile(
    agent="counting",
    instance="partner",
    agent_version="1",
    package_version="0.11.1",
    stage="shadow",
    accounts=("acc-1", "acc-2"),
    keyword="agent-counting-partner",
    poll_seconds=0.25,
    gateway_timeout_seconds=120.0,
    model_alias="",
    prompt_version="",
    started=datetime(2026, 11, 27, 9, 0, tzinfo=UTC),
)


def test_a_profile_is_written_and_read(tmp_path: Path) -> None:
    path = path_for(tmp_path, "counting-partner")
    with Store.open(path) as store:
        assert store.profile() is None
        store.set_profile(PROFILE)

    with Store.open(path, read_only=True) as reader:
        assert reader.profile() == PROFILE


def test_a_second_profile_takes_the_place_of_the_first(tmp_path: Path) -> None:
    later = PROFILE.model_copy(
        update={"stage": "suggest", "instance": None, "accounts": ()}
    )
    with Store.open(path_for(tmp_path, "counting")) as store:
        store.set_profile(PROFILE)
        store.set_profile(later)

        assert store.profile() == later


def test_a_file_older_than_the_profile_reads_as_none(tmp_path: Path) -> None:
    """A reader does not refuse an older file: one of schema 3, before the
    table, has no profile, and that is no error."""
    path = path_for(tmp_path, "counting")
    with closing(sqlite3.connect(path)) as raw, raw:
        for number in (1, 2, 3):
            for statement in MIGRATIONS.step(number).statements:
                raw.execute(inspect.cleandoc(statement))
        raw.execute("PRAGMA user_version = 3")

    with Store.open(path, read_only=True) as reader:
        assert reader.version == 3
        assert reader.profile() is None
