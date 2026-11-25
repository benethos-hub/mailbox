"""An agent renamed does not start beside the state file of its former
name, `categorization` beside `sorting.db`: the cursor and every
decision are in it, and a message moved before would be taken up anew."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.settings import PREFIX

from ..agents_fake import FakeService
from ..agents_helpers import configure

LIST = {"groups": [{"name": "Hosting", "folder": "H", "senders": ["*@h.example"]}]}


@pytest.mark.parametrize("instance", [None, "partner"])
def test_a_state_file_of_the_former_name_is_named_and_not_left_behind(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    instance: str | None,
) -> None:
    configure(monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    listed = tmp_path / "categorization.json"
    listed.write_text(json.dumps(LIST), encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(data))
    monkeypatch.setenv(f"{PREFIX}CATEGORIZATION_FILE", str(listed))
    suffix = f"-{instance}" if instance else ""
    if instance:
        monkeypatch.setenv(f"{PREFIX}INSTANCE", instance)
    (data / f"sorting{suffix}.db").write_bytes(b"")

    assert main(["run", "--agent", "categorization"]) == 2
    err = capsys.readouterr().err
    assert f"sorting{suffix}.db, under a former name of the agent" in err
    assert f"rename it to {(data / f'categorization{suffix}.db').resolve()}" in err
    assert not (data / f"categorization{suffix}.db").exists()

    assert main(["status"]) == 0
    assert "under a former name: rename it" in capsys.readouterr().out


def test_the_state_file_of_its_name_wins_over_one_of_the_former(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    configure(monkeypatch)
    data = tmp_path / "data"
    listed = tmp_path / "categorization.json"
    listed.write_text(json.dumps(LIST), encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(data))
    monkeypatch.setenv(f"{PREFIX}CATEGORIZATION_FILE", str(listed))
    assert main(["run", "--agent", "categorization"]) == 0
    (data / "sorting.db").write_bytes(b"")

    assert main(["run", "--agent", "categorization"]) == 0
    assert main(["status"]) == 0
    assert "former name" not in capsys.readouterr().out
