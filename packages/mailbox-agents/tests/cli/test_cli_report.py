"""The report: decision, evidence and action, with subject and sender."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.cli.report import render, summary
from benethos_mailbox_agents.contract import Action, Shown, ShownAction
from benethos_mailbox_agents.records import (
    LABEL,
    Address,
    Decision,
    Evidence,
    MailMessage,
    MessageRef,
    StepResult,
)
from benethos_mailbox_agents.runtime.review import Entry
from benethos_mailbox_agents.store import ActionRow, MessageRow, Store

from ..agents_fake import ACCOUNT, FakeService, wire_message
from ..agents_helpers import configure

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
REF = MessageRef(account_id=ACCOUNT, message_id="m1")


def test_render_one_entry() -> None:
    entry = Entry(
        row=MessageRow(REF, "done", 0, NOW, NOW, NOW),
        message=MailMessage(
            ref=REF,
            subject="Ihre Rechnung",
            sender=Address(email="billing@supplier.test", name="Billing"),
        ),
        decision=Decision(
            label="invoice",
            source="model",
            fields={"supplier": "Hosting"},
            details={"match": "rule"},
            evidence=(
                Evidence(
                    field=LABEL, value="invoice", quote="Ihre Rechnung", found=True
                ),
                Evidence(field="x", value="y", quote="nowhere", found=False),
            ),
        ),
        model="local-small",
        baseline=Decision(label="invoice", source="baseline"),
        actions=[
            ActionRow(REF, "add_keyword", "invoice", {}, "shadow", False, NOW),
            ActionRow(REF, "move_to_folder", "Invoices/Hosting", {}, "full", True, NOW),
        ],
    )

    assert render([entry]) == [
        f"2026-11-17 09:00  {ACCOUNT}/m1  done",
        "  from: Billing <billing@supplier.test>",
        "  subject: Ihre Rechnung",
        "  decision: invoice (model, local-small) supplier=Hosting match=rule",
        '  evidence: label "Ihre Rechnung" found',
        '  evidence: x "nowhere" NOT found',
        "  baseline: invoice",
        "  action: add_keyword invoice (shadow: would have been done)",
        "  action: move_to_folder Invoices/Hosting (full: done)",
        "",
    ]


def test_the_summary_sees_known_actions_and_leaves_out_others() -> None:
    seen: list[Shown] = []

    class Listening:
        def summarize(self, shown: list[Shown]) -> list[str]:
            seen.extend(shown)
            return []

    entry = Entry(
        row=MessageRow(REF, "done", 0, NOW, NOW, NOW),
        message=None,
        decision=Decision(label="invoice", source="model"),
        model="m",
        baseline=None,
        actions=[
            ActionRow(REF, "move_to_folder", "Invoices", {}, "full", True, NOW),
            ActionRow(REF, "paint_it_red", "", {}, "full", True, NOW),
        ],
    )

    assert summary(Listening(), [entry]) == []  # type: ignore[arg-type]
    assert [item.actions for item in seen] == [
        (ShownAction(Action.MOVE_TO_FOLDER, True),)
    ]


class Talking:
    def __init__(self, said: list[str]) -> None:
        self.said = said

    def summarize(self, shown: list[Shown]) -> list[str]:
        return self.said


def _entry() -> Entry:
    return Entry(
        row=MessageRow(REF, "done", 0, NOW, NOW, NOW),
        message=None,
        decision=Decision(label="invoice", source="model"),
        model="m",
        baseline=None,
    )


def test_the_summary_says_when_it_counts_only_the_shown_messages() -> None:
    entries = [_entry(), _entry()]

    lines = summary(Talking(["by sender:"]), entries, 307)  # type: ignore[arg-type]

    assert lines == [
        "(the lines below count the 2 newest of 307 messages, --limit 307 counts all)",
        "by sender:",
    ]


@pytest.mark.parametrize(
    ("said", "total"),
    [(["by sender:"], 2), (["by sender:"], None), ([], 307)],
)
def test_the_summary_adds_no_note_when_it_sees_all_or_says_nothing(
    said: list[str], total: int | None
) -> None:
    entries = [_entry(), _entry()]

    assert summary(Talking(said), entries, total) == said  # type: ignore[arg-type]


def test_render_a_refused_decision_and_a_message_gone() -> None:
    entry = Entry(
        row=MessageRow(REF, "decided", 0, NOW, NOW, NOW),
        message=MailMessage(ref=REF),
        decision=Decision(label="invoice", source="model", refused="evidence"),
        model="",
        baseline=None,
    )
    gone = Entry(MessageRow(REF, "skipped", 0, NOW, NOW, NOW), None, None, "", None)

    lines = render([entry, gone])

    assert "  from: (no sender)" in lines
    assert "  subject: (none)" in lines
    assert "  decision: invoice (model) refused: evidence" in lines
    assert "  (not fetched: gone from the mailbox or no service)" in lines


def test_report_after_a_run(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    main(["run", "--agent", "counting"])
    service.add(wire_message("m1", subject="Quarterly numbers", sender="a@b.test"))
    service.add(wire_message("m2", subject="Gone soon"))
    main(["run", "--agent", "counting"])
    del service.messages[(ACCOUNT, "m2")]
    capsys.readouterr()

    assert main(["report", "--agent", "counting"]) == 0

    out = capsys.readouterr().out
    assert "subject: Quarterly numbers" in out
    assert "from: a@b.test" in out
    assert "decision: counted (baseline) roles=inbox" in out
    assert "(not fetched" in out

    assert main(["report", "--agent", "counting", "--state", "failed"]) == 0
    assert "nothing recorded yet" in capsys.readouterr().out


def test_report_offline_needs_no_service(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    main(["run", "--agent", "counting"])
    service.add(wire_message("m1"))
    main(["run", "--agent", "counting"])
    monkeypatch.delenv("MAILBOX_AGENTS_SERVICE_TOKEN")
    capsys.readouterr()

    assert main(["report", "--agent", "counting", "--offline", "--limit", "1"]) == 0
    assert "(not fetched" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["report", "--agent", "counting"], "misses MAILBOX_AGENTS_SERVICE_URL"),
        (["report", "--agent", "counting", "--offline"], "no state file"),
        (["report", "--agent", "counting", "--state", "lost"], "--state is one of"),
        (["report", "--agent", "counting", "--limit", "0"], "--limit"),
    ],
)
def test_report_refusals(
    service: FakeService,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    said: str,
) -> None:
    assert main(argv) == 2
    assert said in capsys.readouterr().err


def test_no_control_character_reaches_the_terminal() -> None:
    nasty = "Invoice 42\x1b]0;owned\x07\x1b[2K\r subject: harmless\u2028\x9b"
    entry = Entry(
        row=MessageRow(REF, "done", 0, NOW, NOW, NOW),
        message=MailMessage(
            ref=REF,
            subject=nasty,
            sender=Address(email="a@b.test", name="Billing\naction: fake"),
        ),
        decision=Decision(
            label="invoice",
            source="model",
            fields={"supplier": "x\ny"},
            evidence=(Evidence(field=LABEL, value="invoice", quote=nasty, found=True),),
        ),
        model="m",
        baseline=None,
    )

    lines = render([entry])

    assert all(
        not any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in line)
        and "\u2028" not in line
        for line in lines
    )
    assert "  subject: Invoice 42\\x1b]0;owned\\x07\\x1b[2K\\r subject:" in lines[2]
    assert not any(line.startswith("action: fake") for line in lines)


def test_a_decision_of_a_newer_version_is_shown_without_it(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure(monkeypatch)
    main(["run", "--agent", "counting"])
    service.add(wire_message("m1"))
    main(["run", "--agent", "counting"])
    with Store.open(next(tmp_path.rglob("counting.db"))) as store:
        ref = store.messages(None, 1)[0].ref
        store.add_step(
            ref,
            StepResult(
                step="decision",
                prompt_version="v9",
                model="newer-model",
                result={"label": "counted", "source": "model", "flavour": "Hello Ann"},
                at=datetime.now(UTC),
            ),
            "alias",
        )
    capsys.readouterr()
    caplog.set_level(logging.DEBUG)

    assert main(["report", "--agent", "counting", "--offline"]) == 0

    out = capsys.readouterr().out
    assert "m1" in out
    assert "Hello Ann" not in out + caplog.text
