"""One recognizer of sorting scored alone, in the space of the agent
invoices, and the command eval with --recognizer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.evaluation.gold import GoldItem
from benethos_mailbox_agents.evaluation.report import build, write
from benethos_mailbox_agents.evaluation.run import evaluate
from benethos_mailbox_agents.settings import PREFIX

from ..agents_fake import ACCOUNT, FakeService, wire_message
from ..agents_helpers import configure, settings, wired

WHEN = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
QUOTE = "please find attached the invoice for November"
LIST = {"groups": [{"name": "Hosting", "folder": "H", "senders": ["*@h.example"]}]}


def listed(tmp_path: Path) -> Path:
    path = tmp_path / "sorting.json"
    path.write_text(json.dumps(LIST), encoding="utf-8")
    return path


async def test_the_recognizer_invoice_alone_in_the_space_of_invoices(
    tmp_path: Path,
) -> None:
    agent = Sorting(settings(sorting_file=listed(tmp_path)))
    agent.prepare()
    alone = agent.alone("invoice")
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", subject="Rechnung November", text=f"Hi,\n{QUOTE}.\n")
        )
        world.service.add(
            wire_message("m2", subject="Mahnung", text="Please pay the invoice.")
        )
        world.fake_gateway.answer(
            {"label": "invoice", "near_miss": "none", "quote": QUOTE},
            {
                "label": "other",
                "near_miss": "reminder",
                "quote": "Please pay the invoice",
            },
        )
        items = [
            GoldItem(account_id=ACCOUNT, message_id="m1", label="invoice"),
            GoldItem(
                account_id=ACCOUNT,
                message_id="m2",
                label="other",
                fields={"near_miss": "reminder"},
            ),
        ]

        outcomes = await evaluate(
            alone,
            items,
            reader=world.mailbox,
            gateway=world.gateway,
            store=world.store,
            now=world.clock,
        )
        report = build(alone, "alias", outcomes, WHEN)

    assert (report["agent"], report["prompt_version"]) == ("sorting", "invoice-v5")
    assert report["model"]["agreed"] == 2
    assert report["baseline"]["agreed"] == 2
    assert set(report["model"]["labels"]) == {"invoice", "other"}
    assert "near_miss" in report["model"]["fields"]
    assert "invoice-v5" in write(report, tmp_path / "reports").name
    assert QUOTE not in json.dumps(report)


def test_a_recognizer_that_cannot_be_scored_alone_is_an_error_to_correct(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}SORTING_FILE", str(listed(tmp_path)))
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"account_id": "acc1", "message_id": "m1", "label": "invoice"}\n',
        encoding="utf-8",
    )

    code = main(
        ["eval", "--agent", "sorting", "--recognizer", "topic", "--gold", str(path)]
    )

    assert code == 2
    assert "scores alone the recognizers invoice" in capsys.readouterr().err
