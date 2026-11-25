"""Several processes of one agent, each an instance with a name of its
own: docs/mailbox-agents/concept/configuration.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents.agents.counting.agent import Counting
from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.runtime.metrics import Metrics
from benethos_mailbox_agents.settings import PREFIX, Settings

from ..agents_fake import FakeService, wire_message
from ..agents_helpers import configure


def test_two_instances_keep_a_state_file_each_and_their_own_counts(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    configure(monkeypatch)
    data = tmp_path / "data"
    monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(data))
    monkeypatch.setenv(f"{PREFIX}INSTANCE", "partner")
    assert main(["run", "--agent", "counting"]) == 0
    service.add(wire_message("m1"))
    assert main(["run", "--agent", "counting"]) == 0
    assert "counting/partner: " in capsys.readouterr().out

    monkeypatch.setenv(f"{PREFIX}INSTANCE", "document")
    assert main(["run", "--agent", "counting"]) == 0
    out = capsys.readouterr()
    assert "counting/document: " in out.out
    assert "done=0" in out.out
    assert "counting/document made its state file" in out.err

    assert sorted(p.name for p in data.iterdir() if p.suffix == ".db") == [
        "counting-document.db",
        "counting-partner.db",
    ]
    monkeypatch.setenv(f"{PREFIX}INSTANCE", "partner")
    assert main(["status"]) == 0
    out = capsys.readouterr()
    assert "counting/partner 1: ready" in out.out
    assert "done=1" in out.out


def test_without_an_instance_the_state_file_stays_where_it_was(
    service: FakeService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(tmp_path / "data"))

    assert main(["run", "--agent", "counting"]) == 0

    assert (tmp_path / "data" / "counting.db").is_file()


def test_an_instance_names_the_keyword_the_metrics_and_the_lines() -> None:
    found = Counting(Settings(instance="partner"))
    alone = Counting(Settings())

    assert (found.label, found.state_name, found.keyword) == (
        "counting/partner",
        "counting-partner",
        "agent-counted-partner",
    )
    assert (alone.label, alone.state_name, alone.keyword) == (
        "counting",
        "counting",
        "agent-counted",
    )
    assert Counting(Settings(instance="partner", keyword="agent-x")).keyword == (
        "agent-x"
    )
    text = Metrics("counting", "1", "shadow", "partner").text()
    assert b'instance="partner"' in text


@pytest.mark.parametrize("name", ["Partner", "1st", "a b", "a_b", "x" * 41])
def test_a_wrong_instance_is_refused(name: str) -> None:
    with pytest.raises((ConfigError, ValueError)):
        Settings(instance=name)
