"""What the pages of the cockpit read from the state files."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from benethos_mailbox_agents.cockpit import sources, views
from benethos_mailbox_agents.store import Store

from .cockpit_helpers import NOW, PROFILE, REF, filled, mailbox, newer, older


def test_the_files_of_the_folder_and_its_folders_are_found(tmp_path: Path) -> None:
    filled(tmp_path / "counting" / "counting.db")
    filled(tmp_path / "inquiries.db")
    filled(tmp_path / "other" / "counting.db")
    (tmp_path / "counting" / "counting.db.lock").write_text("")
    (tmp_path / "empty").mkdir()

    found = sources.found(tmp_path)

    assert [file.name for file in found] == [
        "counting",
        "inquiries",
        "other-counting",
    ]
    assert sources.find(tmp_path, "inquiries") == found[1]
    assert sources.find(tmp_path, "../inquiries") is None
    assert sources.found(tmp_path / "none") == []


def test_every_file_is_a_row_and_none_is_an_error(tmp_path: Path) -> None:
    filled(tmp_path / "a" / "counting.db")
    older(tmp_path / "b" / "inquiries.db")
    (tmp_path / "broken.db").write_text("no database, but long enough\n" * 30)
    newer(tmp_path / "future.db")

    rows = {f.name: views.row(f, NOW) for f in sources.found(tmp_path)}

    assert sorted(rows) == ["broken", "counting", "future", "inquiries"]
    counting = rows["counting"]
    assert (counting.agent, counting.kind, counting.state) == (
        "counting",
        "classifier",
        "stopped",
    )
    assert ("done", 1) in {(c.name, c.count) for c in counting.counts}
    assert [(c.name, c.count) for c in counting.labels] == [("invoice", 1)]
    assert rows["inquiries"].facts == ()
    assert rows["inquiries"].state == "stopped"
    assert rows["broken"].state == "unreadable"
    assert "broken.db" in (rows["broken"].problem or "")
    assert str(tmp_path) not in (rows["broken"].problem or "")
    assert "schema version 99" in (rows["future"].problem or "")


@pytest.mark.parametrize(
    ("age", "state"), [(60, "healthy"), (3600, "silent")], ids=["fresh", "old"]
)
def test_a_running_writer_is_healthy_within_the_window_of_its_profile(
    tmp_path: Path, age: int, state: str
) -> None:
    path = filled(tmp_path / "counting.db")
    file = sources.StateFile("counting", path)

    with Store.open(path) as writer:
        writer.set_progress(NOW)
        assert views.row(file, NOW + timedelta(seconds=age)).state == state
    assert views.row(file, NOW).state == "stopped"


def test_without_a_profile_a_running_writer_says_so(tmp_path: Path) -> None:
    path = filled(tmp_path / "counting.db", profile=None)

    with Store.open(path) as writer:
        writer.set_progress(NOW)
        found = views.row(sources.StateFile("counting", path), NOW)

    assert (found.state, found.agent, found.facts) == ("no profile yet", "counting", ())


def test_an_agent_this_version_does_not_know_is_named(tmp_path: Path) -> None:
    path = filled(tmp_path / "x.db", PROFILE.model_copy(update={"agent": "gone"}))

    assert (
        views.row(sources.StateFile("x", path), NOW).kind == "unknown to this version"
    )


async def test_a_subject_is_escaped_and_without_a_service_only_ids_show(
    tmp_path: Path,
) -> None:
    file = sources.StateFile("counting", filled(tmp_path / "counting.db"))

    shown = await views.results(file, mailbox, limit=10)
    bare = await views.results(file, None, limit=10)

    assert shown[0].subject == "Your invoice\\x1b[2J <script>alert(1)</script>"
    assert shown[0].sender == "Billing\\u202e <billing@example.org>"
    assert (bare[0].subject, bare[0].sender) == (None, None)
    assert (bare[0].account_id, bare[0].message_id, bare[0].label) == (
        "acc1",
        "m1",
        "invoice",
    )


async def test_one_message_shows_its_evidence_steps_and_actions(tmp_path: Path) -> None:
    file = sources.StateFile("counting", filled(tmp_path / "counting.db"))

    found = await views.message(file, REF, None)
    gone = await views.message(file, REF.model_copy(update={"message_id": "m9"}), None)

    assert found is not None
    assert gone is None
    assert [quote.quote for quote in found.evidence] == [
        "Your invoice\\x1b[2J <script>alert(1)</script>"
    ]
    assert [step.step for step in found.steps] == ["decision"]
    assert [(a.action, a.executed) for a in found.result.actions] == [
        ("add_keyword", False)
    ]
