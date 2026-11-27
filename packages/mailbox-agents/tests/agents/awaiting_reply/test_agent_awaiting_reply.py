"""The agent awaiting_reply: open items, deadlines in working days, the
closing rules of docs/mailbox-agents/concept/agent-awaiting-reply.md, and each known
miss."""

from __future__ import annotations

import time
import unicodedata
from datetime import UTC, datetime

import pytest

from benethos_mailbox_agents.agents.awaiting_reply.schema import (
    render,
)
from benethos_mailbox_agents.agents.awaiting_reply.text import (
    add_working_days,
    asks,
    automatic,
    own_text,
)
from benethos_mailbox_agents.records import Address, MailMessage

from ...agents_fake import ACCOUNT
from .awaiting_reply_helpers import (
    ASK,
    PARTNER,
    QUESTION,
    World,
    expects,
    no_reply,
    ref,
    sent,
)

# -- the text rules --------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "due"),
    [
        (datetime(2026, 11, 16, 9, tzinfo=UTC), datetime(2026, 11, 19, 9, tzinfo=UTC)),
        (datetime(2026, 11, 20, 9, tzinfo=UTC), datetime(2026, 11, 25, 9, tzinfo=UTC)),
        (datetime(2026, 11, 21, 9, tzinfo=UTC), datetime(2026, 11, 26, 9, tzinfo=UTC)),
    ],
    ids=["monday", "friday", "saturday"],
)
def test_working_days_skip_the_weekend(start: datetime, due: datetime) -> None:
    assert add_working_days(start, 3) == due


def test_decomposed_text_is_read_like_composed_text() -> None:
    text = unicodedata.normalize(
        "NFD",
        "Könnten Sie mir den Entwurf schicken.\n\n-- Ursprüngliche Nachricht --\nAlt.",
    )

    assert asks(text)
    assert "Alt." not in own_text(text)


def test_own_text_leaves_the_quote_out() -> None:
    text = "Danke.\n\nAm 12.11.2026 schrieb Partner <p@p.example>:\n> Frage?"

    assert own_text(text) == "Danke."
    assert own_text("Ok\n> quoted") == "Ok"


@pytest.mark.parametrize("start", ["am ", "on "], ids=["german", "english"])
def test_a_long_line_does_not_hold_up_the_loop(start: str) -> None:
    """A line that starts like a quote and never ends like one: the
    patterns of the quote must not try every split of a megabyte."""
    line = start + ("schrieb " if start == "am " else "wrote ") * 130_000
    began = time.perf_counter()

    assert own_text(line) == line.strip()
    assert time.perf_counter() - began < 0.1


@pytest.mark.parametrize(
    ("text", "asking"),
    [
        (ASK, True),
        ("Guten Tag,\n\nbitte teilen Sie mir die Adresse mit.\n\nDanke", True),
        ("Danke dir, passt so.\n\nGrüße", False),
        ("Kurz", False),
        ("Hier die Unterlagen, wie besprochen.\n\n> Can you send it?", False),
    ],
)
def test_the_baseline_reads_the_last_paragraph_written(text: str, asking: bool) -> None:
    assert asks(text) is asking


@pytest.mark.parametrize(
    ("sender", "subject", "auto"),
    [
        ("office@client.example", "Automatische Antwort: Angebot", True),
        ("office@client.example", "Out of Office: Angebot", True),
        ("mailer-daemon@client.example", "Failure", True),
        ("noreply@client.example", "Re: Angebot", True),
        ("office@client.example", "Re: Angebot", False),
    ],
)
def test_an_automatic_answer_by_sender_and_subject(
    sender: str, subject: str, auto: bool
) -> None:
    message = MailMessage(ref=ref("x"), sender=Address(email=sender), subject=subject)

    assert automatic(message) is auto


def test_the_model_is_given_recipients_subject_and_own_text() -> None:
    message = MailMessage(
        ref=ref("x"),
        to=(Address(email=PARTNER),),
        subject="Angebot",
        text="Bis Freitag?\n> old question",
    )

    assert render(message) == f"To: {PARTNER}\nSubject: Angebot\n\nBis Freitag?"


# -- opening, the deadline and the keyword ----------------------------------------


async def test_a_sent_message_that_asks_waits_and_is_marked_when_due(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))

    await awaiting_world.run()

    item = awaiting_world.item("s1")
    assert item.is_open and item.due == datetime(2026, 11, 19, 9, tzinfo=UTC)
    assert awaiting_world.keywords("s1") == []

    awaiting_world.clock.advance(days=3, minutes=1)
    await awaiting_world.run()

    assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]
    assert awaiting_world.item("s1").keyword_set
    assert awaiting_world.w.service.messages[(ACCOUNT, "s1")]["folder_ids"] == ["sent"]


async def test_a_sent_message_that_does_not_ask_opens_nothing(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", "Danke dir, passt so."), "message.sent")
    awaiting_world.w.fake_gateway.answer(no_reply("Danke dir, passt so."))

    await awaiting_world.run()

    assert awaiting_world.item("s1") is None


async def test_a_quote_not_in_the_message_opens_nothing(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects("Please answer at once"))

    await awaiting_world.run()

    assert awaiting_world.item("s1") is None
