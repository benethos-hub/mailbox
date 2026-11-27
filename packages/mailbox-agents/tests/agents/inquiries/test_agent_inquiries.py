"""The agent inquiries: the label, its evaluation, and later its fields."""

from __future__ import annotations

import unicodedata
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from benethos_mailbox_agents.agents.inquiries.agent import Inquiries
from benethos_mailbox_agents.agents.inquiries.patterns import DATE, RATE, load_patterns
from benethos_mailbox_agents.agents.inquiries.schema import (
    FIELDS,
    MAX_ADDRESS,
    MAX_ANSWER_TOTAL,
    MAX_NAME,
    MAX_SUBJECT,
    MAX_TEXT,
    Inquiry,
    parts,
    render,
)
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.evaluation.gold import load_gold
from benethos_mailbox_agents.evaluation.report import build
from benethos_mailbox_agents.evaluation.run import evaluate
from benethos_mailbox_agents.records import Address, MailMessage, MessageRef

from ...agents_fake import ACCOUNT, invented
from ...agents_helpers import ROOT, Wired, run, settings, wired

DATA = Path(__file__).resolve().parents[2] / "data"
PATTERNS = ROOT / "config" / "benethos-mailbox-agents" / "inquiries.example.json"
MESSAGES = {m["id"]: m for m in invented("invented-inquiries.json")}


def said(label: str, quote: str, **fields: tuple[str, str]) -> dict[str, Any]:
    """An answer of the model: the label, and each field as value and quote,
    or null."""
    found: dict[str, Any] = {"label": label, "quote": quote}
    for name in FIELDS:
        given = fields.get(name)
        found[name] = None if given is None else {"value": given[0], "quote": given[1]}
    return found


def agent(stage: str = "full", **values: Any) -> Inquiries:
    return Inquiries(settings(stage=stage, **values))


@pytest.fixture
async def inquiries_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        for message in MESSAGES.values():
            found.service.add(message, change=None)
        yield found


def _message(message_id: str) -> MailMessage:
    raw = MESSAGES[message_id]
    return MailMessage.model_validate(
        {
            "ref": {"account_id": ACCOUNT, "message_id": message_id},
            "subject": raw["subject"],
            "sender": raw["from"],
            "text": raw["text_body"],
        }
    )


# -- the patterns and the rules ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "date", "rate"),
    [
        ("ab 01.02.2027", True, False),
        ("Start 2027-01-15", True, False),
        ("bis 95 EUR", False, True),
        ("90 €/h", False, True),
        ("EUR 700", False, True),
        ("Version 3.11", False, False),
    ],
)
def test_dates_and_rates(text: str, date: bool, rate: bool) -> None:
    assert bool(DATE.search(text)) is date
    assert bool(RATE.search(text)) is rate


def test_the_patterns_file(tmp_path: Path) -> None:
    found = load_patterns(PATTERNS)

    assert found.sender_known(Address(email="jana@staffing.example"))
    assert found.sender_known(Address(email="x@EU.Staffing.example"))
    assert not found.sender_known(Address(email="x@client.example"))
    assert not found.sender_known(None)
    assert load_patterns(None).domains == ()

    broken = tmp_path / "p.json"
    broken.write_text('{"domains": [""]}', encoding="utf-8")
    with pytest.raises(
        ConfigError, match="p.json: domains: Value error, an empty entry"
    ):
        load_patterns(broken)
    with pytest.raises(ConfigError, match="cannot be read"):
        load_patterns(tmp_path / "none.json")


def test_a_patterns_file_with_the_mark_of_utf8_is_read(tmp_path: Path) -> None:
    listed = tmp_path / "p.json"
    listed.write_text('{"domains": ["staffing.example"]}', encoding="utf-8-sig")

    assert load_patterns(listed).sender_known(Address(email="jana@staffing.example"))


def test_a_phrase_is_found_in_decomposed_text(tmp_path: Path) -> None:
    listed = tmp_path / "p.json"
    listed.write_text('{"phrases": ["Rahmenvertrag für"]}', encoding="utf-8")
    text = unicodedata.normalize(
        "NFD", "Wir suchen für einen Kunden, Rahmenvertrag für 2027."
    )

    found = load_patterns(listed).phrases_in(text)

    assert "für einen kunden" in found
    assert "rahmenvertrag für" in found


def test_the_baseline_on_the_invented_set() -> None:
    rules = agent(inquiries_patterns_file=PATTERNS)
    found = {
        item.message_id: rules.baseline(_message(item.message_id)).label
        for item in load_gold(DATA / "gold-inquiries.jsonl")
    }

    assert found == {
        "inq-staffing": "inquiry",
        "inq-direct": "inquiry",
        "inq-english": "inquiry",
        "job-digest": "other",
        "meeting": "other",
        "invoice": "other",
        "personal": "other",
    }


def test_a_wrong_patterns_file_stops_the_start(tmp_path: Path) -> None:
    broken = tmp_path / "p.json"
    broken.write_text("{", encoding="utf-8")

    with pytest.raises(ConfigError):
        agent(inquiries_patterns_file=broken).prepare()


# -- the label -----------------------------------------------------------------------


def keywords(inquiries_world: Wired, message_id: str) -> list[str]:
    return inquiries_world.service.messages[(ACCOUNT, message_id)]["keywords"]


async def test_an_inquiry_is_marked(inquiries_world: Wired) -> None:
    inquiries_world.fake_gateway.answer(said("inquiry", "suchen wir ab 01.02.2027"))

    assert await run(inquiries_world, "inq-staffing", agent()) == "done"
    assert keywords(inquiries_world, "inq-staffing") == ["agent-inquiry"]


async def test_another_message_is_not(inquiries_world: Wired) -> None:
    inquiries_world.fake_gateway.answer(said("other", "10 neue Jobs für Sie"))

    assert await run(inquiries_world, "job-digest", agent()) == "done"
    assert keywords(inquiries_world, "job-digest") == []


async def test_a_label_without_its_quote_is_not_acted_on(
    inquiries_world: Wired,
) -> None:
    inquiries_world.fake_gateway.answer(said("inquiry", "a great project for you"))

    assert await run(inquiries_world, "personal", agent()) == "decided"
    assert keywords(inquiries_world, "personal") == []


async def test_the_label_has_an_evaluation_of_its_own(inquiries_world: Wired) -> None:
    items = load_gold(DATA / "gold-inquiries.jsonl")
    quotes = {
        "inq-staffing": ("inquiry", "für einen Kunden aus der Logistik"),
        "inq-direct": ("inquiry", "wir suchen ab März 2027 Unterstützung"),
        "inq-english": ("inquiry", "we are looking for a Senior Python Engineer"),
        "job-digest": ("other", "10 neue Jobs für Sie"),
        "meeting": ("other", "Termin zum laufenden Projekt"),
        "invoice": ("other", "Anbei Ihre Rechnung"),
        "personal": ("inquiry", "Hast du am Samstag Zeit?"),
    }
    for item in items:
        label, quote = quotes[item.message_id]
        inquiries_world.fake_gateway.answer(said(label, quote))
    the_agent = agent(inquiries_patterns_file=PATTERNS)

    outcomes = await evaluate(
        the_agent,
        items,
        reader=inquiries_world.mailbox,
        gateway=inquiries_world.gateway,
        store=inquiries_world.store,
        now=inquiries_world.clock,
    )
    report = build(the_agent, "alias", outcomes, inquiries_world.clock())

    model, rules = report["model"], report["baseline"]
    assert model["labels"]["inquiry"] == {
        "true_positive": 3,
        "false_positive": 1,
        "false_negative": 0,
        "precision": 0.75,
        "recall": 1.0,
    }
    assert rules["labels"]["inquiry"]["recall"] == 1.0
    assert rules["agreed"] == 7


# -- the fields --------------------------------------------------------------------


async def test_each_field_with_its_quote(inquiries_world: Wired) -> None:
    inquiries_world.fake_gateway.answer(
        said(
            "inquiry",
            "Projektanfrage: Python-Entwicklung, remote",
            role=("Python-Entwickler", "Unterstützung als Python-Entwickler"),
            start=("01.02.2027", "ab 01.02.2027"),
            rate=("bis 95 EUR", "Stundensatz bis 95 EUR"),
            location=("Berlin", "Einsatzort Berlin"),
            end=("", "6 Monate"),
        )
    )

    assert await run(inquiries_world, "inq-staffing", agent()) == "done"

    ref = MessageRef(account_id=ACCOUNT, message_id="inq-staffing")
    found = inquiries_world.store.step(
        ref, "decision", Inquiries.prompt_version, "alias"
    )
    assert found is not None
    assert found.result["fields"] == {
        "role": "Python-Entwickler",
        "start": "01.02.2027",
        "rate": "bis 95 EUR",
    }
    dropped = [e["field"] for e in found.result["evidence"] if not e["found"]]
    assert dropped == ["location"]


async def test_another_message_has_no_fields(inquiries_world: Wired) -> None:
    inquiries_world.fake_gateway.answer(
        said("other", "10 neue Jobs für Sie", role=("Data Engineer", "Data Engineer"))
    )

    await run(inquiries_world, "job-digest", agent())

    ref = MessageRef(account_id=ACCOUNT, message_id="job-digest")
    found = inquiries_world.store.step(
        ref, "decision", Inquiries.prompt_version, "alias"
    )
    assert found is not None and found.result["fields"] == {}


def test_the_prompt_names_every_field() -> None:
    system = agent().system

    assert all(f"`{name}`" in system for name in FIELDS)
    assert "{fields}" not in system


async def test_the_fields_have_an_evaluation_of_their_own(
    inquiries_world: Wired,
) -> None:
    items = [i for i in load_gold(DATA / "gold-inquiries.jsonl") if i.fields]
    inquiries_world.fake_gateway.answer(
        said(
            "inquiry",
            "Projektanfrage: Python-Entwicklung, remote",
            role=("Python-Entwickler", "Unterstützung als Python-Entwickler"),
            duration=("sechs Monate", "für 6 Monate"),
            location=("Berlin", "Einsatzort Berlin"),
            intermediary=("Jana", "Viele Grüße\nJana"),
        ),
        said(
            "inquiry",
            "wir suchen ab März 2027 Unterstützung",
            rate=("90 €/h", "Das Budget liegt bei 90 €/h"),
        ),
        said("inquiry", "we are looking for a Senior Python Engineer"),
    )
    the_agent = agent()

    outcomes = await evaluate(
        the_agent,
        items,
        reader=inquiries_world.mailbox,
        gateway=inquiries_world.gateway,
        store=inquiries_world.store,
        now=inquiries_world.clock,
    )
    fields = build(the_agent, "alias", outcomes, inquiries_world.clock())["model"][
        "fields"
    ]

    assert fields["role"] == {
        "right": 1,
        "wrong": 0,
        "missing": 2,
        "invented": 0,
        "empty": 0,
    }
    assert fields["duration"]["wrong"] == 1
    assert fields["location"]["missing"] == 2
    assert fields["intermediary"] == {
        "right": 0,
        "wrong": 0,
        "missing": 0,
        "invented": 1,
        "empty": 2,
    }
    assert fields["rate"]["right"] == 1


def test_a_stranger_cannot_blow_up_the_call() -> None:
    """Subject and name are the sender's choice: each is cut, the same for
    the model and for the evidence check."""
    message = MailMessage(
        ref=MessageRef(account_id=ACCOUNT, message_id="m1"),
        sender=Address(email="jobs@agency.example", name="N" * 20_000),
        subject="S" * 20_000,
        text="T" * 20_000,
    )

    rendered = render(message)

    assert len(rendered) < MAX_TEXT + MAX_SUBJECT + MAX_NAME + 200
    assert parts(message) == [
        "N" * MAX_NAME + " <jobs@agency.example>",
        "S" * MAX_SUBJECT,
        "T" * MAX_TEXT,
    ]
    assert all(part in rendered for part in parts(message))


def test_a_long_address_is_cut_for_the_model_and_the_check() -> None:
    address = "a" * 100_000 + "@agency.example"
    message = MailMessage(
        ref=MessageRef(account_id=ACCOUNT, message_id="m1"),
        sender=Address(email=address, name=None),
        subject="Anfrage",
        text="Text",
    )

    rendered = render(message)

    assert len(rendered) < MAX_ADDRESS + 200
    assert parts(message)[0] == address[:MAX_ADDRESS]
    assert parts(message)[0] in rendered


def _answer(text: str) -> dict[str, object]:
    """An answer of inquiries with every field filled with ``text``."""
    fields: dict[str, object] = {
        name: {"value": text, "quote": text} for name in FIELDS
    }
    return {"label": "inquiry", "quote": text, **fields}


def test_an_answer_longer_than_its_total_is_refused() -> None:
    # 29 strings of 300 characters each: every one within its own limit.
    assert 29 * 300 > MAX_ANSWER_TOTAL
    with pytest.raises(ValidationError, match=f"more than {MAX_ANSWER_TOTAL}"):
        Inquiry.model_validate(_answer("x" * 300))


def test_an_answer_of_ordinary_length_is_taken() -> None:
    found = Inquiry.model_validate(_answer("Senior Java Developer ab 01.12."))

    assert found.role is not None
    assert found.role.value == "Senior Java Developer ab 01.12."
