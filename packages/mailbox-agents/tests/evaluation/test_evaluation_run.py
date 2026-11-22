"""The run over a gold set, its report, and the command eval."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from benethos_mailbox_agents.agents.invoices.agent import Invoices
from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.errors import GatewayUnavailableError
from benethos_mailbox_agents.evaluation.gold import GoldItem
from benethos_mailbox_agents.evaluation.report import build, render, write
from benethos_mailbox_agents.evaluation.run import evaluate
from benethos_mailbox_agents.evaluation.scoring import Outcome
from benethos_mailbox_agents.records import Decision

from ..agents_fake import ACCOUNT, FakeService, wire_message
from ..agents_helpers import Echo, configure, settings, wired

WHEN = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def gold(message_id: str, label: str) -> GoldItem:
    return GoldItem(account_id=ACCOUNT, message_id=message_id, label=label)


async def test_the_model_beside_the_rules(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", subject="Your invoice", text="Attached."))
        world.service.add(
            wire_message("m2", subject="A bill", text="Please pay me now.")
        )
        world.service.add(wire_message("m3", subject="Hello", text="Hi."))
        world.fake_gateway.answer(
            {"label": "match", "quote": "Your invoice"},
            {"label": "match", "quote": "Please pay me now."},
            {"label": "match", "quote": "not in the mail"},
        )
        items = [
            gold("m1", "match"),
            gold("m2", "match"),
            gold("m3", "other"),
            gold("gone", "other"),
        ]
        agent = Echo(settings())

        outcomes = await evaluate(
            agent,
            items,
            reader=world.mailbox,
            gateway=world.gateway,
            store=world.store,
            now=world.clock,
        )
        report = build(agent, "alias", outcomes, WHEN)

    model, rules = report["model"], report["baseline"]
    assert (model["agreed"], model["refused"], model["unanswered"]) == (2, 1, 2)
    assert rules["agreed"] == 2
    assert model["labels"]["match"]["recall"] == 1.0
    assert rules["labels"]["match"]["recall"] == 0.5
    assert report["models_reported"] == ["reported-model"]
    assert report["unanswered_because"] == {"fetch:gone": 1}
    assert report["per_message"]["tokens_in"] == 90.0
    text = json.dumps(report)
    assert "m1" not in text and "Your invoice" not in text


async def test_a_refused_answer_is_unanswered_and_named(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1"))
        world.fake_gateway.answer({"label": "maybe", "quote": "x"})

        outcomes = await evaluate(
            Echo(settings()),
            [gold("m1", "other")],
            reader=world.mailbox,
            gateway=world.gateway,
            store=world.store,
            now=world.clock,
        )

    assert outcomes[0].failure == "answer:schema"


async def test_a_gateway_that_is_away_ends_the_run(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1"))
        world.fake_gateway.answer(httpx.Response(503))

        with pytest.raises(GatewayUnavailableError):
            await evaluate(
                Echo(settings()),
                [gold("m1", "other")],
                reader=world.mailbox,
                gateway=world.gateway,
                store=world.store,
                now=world.clock,
            )


def outcome(label: str, fields: dict[str, str | None], found: str) -> Outcome:
    return Outcome(
        item=GoldItem(account_id=ACCOUNT, message_id="m1", label=label, fields=fields),
        baseline=Decision(
            label=found,
            source="baseline",
            fields={k: v for k, v in fields.items() if v is not None},
        ),
        decision=None,
    )


def test_a_report_names_no_label_or_field_the_agent_does_not_declare(
    tmp_path: Path,
) -> None:
    """A group of sorting is named by its owner, often after a person, and
    a report is versioned: such a name becomes a placeholder."""
    outcomes = [
        outcome("Dr Jane Invented", {"free text": "x"}, "Dr Jane Invented"),
        outcome("Acme Invented", {"free text": None}, "none"),
        outcome("none", {}, "Dr Jane Invented"),
    ]

    report = build(Sorting(settings()), "", outcomes, WHEN)

    text = (write(report, tmp_path)).read_text(encoding="utf-8")
    assert "Jane" not in text
    assert "Acme" not in text
    assert "free text" not in text
    labels = report["baseline"]["labels"]
    assert sorted(labels) == ["label-1", "label-2", "none"]
    # Numbered by the sorted names: Acme first, then Dr Jane.
    assert labels["label-1"]["false_negative"] == 1
    assert labels["label-2"] == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 0,
        "precision": 0.5,
        "recall": 1.0,
    }
    assert labels["none"]["false_positive"] == 1
    assert report["model"]["labels"].keys() == labels.keys()
    assert report["baseline"]["fields"]["field-1"]["right"] == 1
    assert report["baseline"]["fields"]["field-1"]["empty"] == 1


def test_a_report_names_the_labels_and_fields_an_agent_declares() -> None:
    outcomes = [
        outcome("invoice", {}, "invoice"),
        outcome("other", {"near_miss": "reminder"}, "other"),
    ]

    report = build(Invoices(settings()), "", outcomes, WHEN)

    assert sorted(report["baseline"]["labels"]) == ["invoice", "other"]
    assert sorted(report["baseline"]["fields"]) == ["near_miss"]


def test_the_report_file_is_named_by_date_versions_and_model(tmp_path: Path) -> None:
    report = build(Echo(settings()), "local/small:q4", [], WHEN)

    path = write(report, tmp_path)

    assert path == tmp_path / "echo" / "2026-11-17-v1-p1-local-small-q4.json"
    assert json.loads(path.read_text(encoding="utf-8"))["gold_messages"] == 0
    assert render(report)[0].startswith("echo 1, prompt p1, model local/small:q4")


def test_eval_on_the_command_line(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    configure(monkeypatch)
    service.add(wire_message("m1"), change=None)
    service.add(wire_message("m2"), change=None)
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"account_id": "acc1", "message_id": "m1", "label": "counted"}\n'
        '{"account_id": "acc1", "message_id": "m2", "label": "other"}\n',
        encoding="utf-8",
    )

    assert main(["eval", "--agent", "counting", "--gold", str(path)]) == 0

    out = capsys.readouterr().out
    assert "accuracy: model 50.0 %, rules 50.0 %" in out
    written = list(
        (tmp_path / "reports" / "mailbox-agents" / "counting").glob("*.json")
    )
    assert len(written) == 1
    assert "no-prompt-no-model" in written[0].name


def test_eval_outside_the_repository_reports_beside_the_state_files(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch)
    (tmp_path / "config" / "benethos-mailbox-agents").rmdir()
    data = tmp_path / "state"
    monkeypatch.setenv("MAILBOX_AGENTS_DATA_DIR", str(data))
    service.add(wire_message("m1"), change=None)
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"account_id": "acc1", "message_id": "m1", "label": "counted"}\n',
        encoding="utf-8",
    )

    assert main(["eval", "--agent", "counting", "--gold", str(path)]) == 0

    assert len(list((data / "reports" / "counting").glob("*.json"))) == 1
    assert not (tmp_path / "reports").exists()


def test_eval_against_another_line_is_an_error_to_correct(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    configure(monkeypatch)
    service.add(wire_message("m1"), change=None)
    service.version = "0.99.0"
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"account_id": "acc1", "message_id": "m1", "label": "counted"}\n',
        encoding="utf-8",
    )

    assert main(["eval", "--agent", "counting", "--gold", str(path)]) == 2

    assert "the mailbox service runs '0.99.0'" in capsys.readouterr().err
    assert service.health_asked == 1
    assert service.requests == []
    assert not (tmp_path / "reports").exists()


def test_eval_needs_a_gold_file(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)

    assert main(["eval", "--agent", "counting", "--gold", "none.jsonl"]) == 2
    assert "no gold file" in capsys.readouterr().err
