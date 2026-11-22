"""The agent awaiting_reply: open items, deadlines in working days, the
closing rules of docs/mailbox-agents/concept/agent-awaiting-reply.md, and each known
miss."""

from __future__ import annotations

import time
import unicodedata
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from benethos_mailbox_agents.agents.awaiting_reply.agent import AwaitingReply
from benethos_mailbox_agents.agents.awaiting_reply.schema import (
    MAX_SUBJECT,
    MAX_TEXT,
    parts,
    render,
)
from benethos_mailbox_agents.agents.awaiting_reply.text import (
    add_working_days,
    asks,
    automatic,
    own_text,
)
from benethos_mailbox_agents.records import Address, MailMessage, MessageRef
from benethos_mailbox_agents.runtime.loop import Worker

from ..fakes import ACCOUNT, wire_message
from ..helpers import Clock, Wired, settings, wired

ME = "me@example.test"
PARTNER = "partner@partner.example"
# Monday 16 November 2026, nine in the morning.
MONDAY = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def ref(message_id: str) -> MessageRef:
    return MessageRef(account_id=ACCOUNT, message_id=message_id)


def sent(
    message_id: str,
    text: str,
    *,
    date: str = "2026-11-16T09:00:00+00:00",
    thread: str = "t1",
    to: str = PARTNER,
) -> dict[str, Any]:
    return wire_message(
        message_id,
        folder_ids=["sent"],
        sender=ME,
        to=[to],
        subject="Angebot",
        text=text,
        thread_id=thread,
        date=date,
    )


def received(
    message_id: str,
    *,
    sender: str = PARTNER,
    subject: str = "Re: Angebot",
    date: str = "2026-11-17T09:00:00+00:00",
    thread: str | None = "t1",
) -> dict[str, Any]:
    return wire_message(
        message_id,
        sender=sender,
        subject=subject,
        text="Gern, morgen.",
        thread_id=thread,
        date=date,
    )


def expects(quote: str) -> dict[str, Any]:
    return {"expects_reply": True, "quote": quote}


def no_reply(quote: str) -> dict[str, Any]:
    return {"expects_reply": False, "quote": quote}


ASK = "Hallo,\n\nkönnten Sie mir bis Freitag Ihr Angebot schicken?\n\nGrüße"
QUESTION = "könnten Sie mir bis Freitag Ihr Angebot schicken?"


class World:
    def __init__(self, wired_: Wired, stage: str = "full") -> None:
        self.w = wired_
        self.w.clock.moment = MONDAY
        self.agent = AwaitingReply(settings(stage=stage, reply_days=3))
        self.worker = Worker(
            agent=self.agent,
            store=wired_.store,
            mailbox=wired_.mailbox,
            gateway=wired_.gateway,
            now=wired_.clock,
        )

    async def start(self) -> None:
        await self.worker.run_pass()

    async def run(self) -> None:
        await self.worker.run_pass()

    @property
    def clock(self) -> Clock:
        return self.w.clock

    def add(self, message: dict[str, Any], change: str = "message.created") -> None:
        self.w.service.add(message, change)

    def item(self, message_id: str) -> Any:
        return self.w.store.item(ref(message_id))

    def keywords(self, message_id: str) -> list[str]:
        return self.w.service.messages[(ACCOUNT, message_id)]["keywords"]


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[World]:
    async with wired(tmp_path) as found:
        made = World(found)
        await made.start()
        yield made


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
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))

    await world.run()

    item = world.item("s1")
    assert item.is_open and item.due == datetime(2026, 11, 19, 9, tzinfo=UTC)
    assert world.keywords("s1") == []

    world.clock.advance(days=3, minutes=1)
    await world.run()

    assert world.keywords("s1") == ["agent-awaiting-reply"]
    assert world.item("s1").keyword_set
    assert world.w.service.messages[(ACCOUNT, "s1")]["folder_ids"] == ["sent"]


async def test_a_sent_message_that_does_not_ask_opens_nothing(world: World) -> None:
    world.add(sent("s1", "Danke dir, passt so."), "message.sent")
    world.w.fake_gateway.answer(no_reply("Danke dir, passt so."))

    await world.run()

    assert world.item("s1") is None


async def test_a_quote_not_in_the_message_opens_nothing(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects("Please answer at once"))

    await world.run()

    assert world.item("s1") is None


# -- what closes an item ------------------------------------------------------------


async def test_a_reply_to_a_sent_message_deleted_since_blocks_nothing(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    del world.w.service.messages[(ACCOUNT, "s1")]

    world.add(received("r1"))
    await world.run()

    found = world.w.store.message(ref("r1"))
    assert found is not None and found.state == "done"
    assert (world.item("s1").is_open, world.item("s1").reason) == (
        False,
        "message_gone",
    )
    assert world.w.store.cursor() == world.w.service.state


async def test_a_gateway_that_is_away_holds_up_neither_tick_nor_replies(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    world.add(sent("s2", ASK, thread="t2"), "message.sent")
    world.add(sent("s3", ASK, thread="t3"), "message.sent")
    world.add(received("r9", thread="t9"))
    world.w.fake_gateway.answer(httpx.Response(503))

    await world.run()

    assert world.keywords("s1") == ["agent-awaiting-reply"]
    states = {m: world.w.store.message(ref(m)) for m in ("s2", "s3", "r9")}
    assert {m: (row.state, row.attempts) for m, row in states.items() if row} == {
        "s2": ("pending", 0),
        "s3": ("pending", 0),
        "r9": ("done", 0),
    }
    assert len(world.w.fake_gateway.requests) == 2


async def test_no_tick_while_a_message_waits_for_another_reason(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    world.add(sent("s2", ASK, thread="t2"), "message.sent")
    world.w.fake_gateway.answer(httpx.Response(503))
    await world.run()
    assert world.w.store.message(ref("s2")) is not None
    assert world.worker._only_gateway_waits()

    # One due beyond the batch of this pass, such as a reply.
    world.w.store.enqueue(ref("late"), world.clock())

    assert not world.worker._only_gateway_waits()


async def staged(tmp_path: Path, stage: str) -> AsyncIterator[World]:
    async with wired(tmp_path) as found:
        made = World(found, stage)
        await made.start()
        yield made


async def _due(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    await world.run()


async def test_shadow_records_an_item_once_and_a_star_closes_nothing(
    tmp_path: Path,
) -> None:
    async for world in staged(tmp_path, "shadow"):
        await _due(world)
        assert world.keywords("s1") == []
        assert [a.executed for a in world.w.store.actions(ref("s1"))] == [False]

        world.w.service.change("message.updated", "s1")
        world.clock.advance(days=1)
        await world.run()

        assert world.item("s1").is_open
        assert not world.item("s1").keyword_set
        assert len(world.w.store.actions(ref("s1"))) == 1


async def test_a_keyword_the_service_refused_is_offered_again(tmp_path: Path) -> None:
    async for world in staged(tmp_path, "full"):
        world.w.service.write_refusal = (422, "keyword_refused")
        await _due(world)
        assert world.keywords("s1") == []
        assert not world.item("s1").keyword_set

        world.w.service.write_refusal = None
        world.clock.advance(days=1)
        await world.run()

        assert world.keywords("s1") == ["agent-awaiting-reply"]
        assert world.item("s1").keyword_set


async def test_an_item_whose_sent_message_is_gone_closes_on_the_tick(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    del world.w.service.messages[(ACCOUNT, "s1")]
    world.clock.advance(days=4)

    await world.run()

    found = world.item("s1")
    assert found.closed is not None and found.reason == "message_gone"
    assert world.w.store.due_items(world.clock()) == []


async def test_after_shadow_the_keyword_stage_sets_the_keyword(tmp_path: Path) -> None:
    async for world in staged(tmp_path, "shadow"):
        await _due(world)
        assert world.keywords("s1") == []

        moment = world.clock.moment
        keyword = World(world.w, "keyword")
        world.clock.moment = moment
        world.clock.advance(days=1)
        await keyword.run()

        assert world.keywords("s1") == ["agent-awaiting-reply"]
        assert world.item("s1").keyword_set


async def test_a_reply_decided_before_its_sent_message_opens_nothing(
    world: World,
) -> None:
    world.add(received("r1"), "")
    world.add(sent("s1", ASK), "")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.worker.backfill(30)
    order = [row.ref.message_id for row in world.w.store.messages("pending")]
    assert set(order) == {"r1", "s1"}

    await world.worker.process_due()
    world.clock.advance(days=4)
    await world.run()

    assert world.item("s1") is None
    assert world.keywords("s1") == []


async def test_a_later_automatic_answer_still_opens_the_item(world: World) -> None:
    world.add(received("r1", sender="noreply@partner.example"), "")
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))

    await world.run()

    assert world.item("s1").is_open


async def test_taking_a_message_up_again_reopens_nothing(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    await world.run()
    assert world.keywords("s1") == ["agent-awaiting-reply"]
    world.w.service.messages[(ACCOUNT, "s1")]["keywords"] = []
    world.w.service.change("message.updated", "s1")
    await world.run()
    assert world.item("s1").reason == "keyword_removed"

    await world.worker.backfill(30, again=True)
    world.clock.advance(days=1)
    await world.run()

    assert world.item("s1").reason == "keyword_removed"
    assert world.keywords("s1") == []


async def test_a_keyword_the_service_answers_in_another_case(tmp_path: Path) -> None:
    async with wired(tmp_path) as found:
        world = World(found)
        world.agent = AwaitingReply(
            settings(stage="full", reply_days=3, keyword="awaiting-reply")
        )
        world.worker = Worker(
            agent=world.agent,
            store=found.store,
            mailbox=found.mailbox,
            gateway=found.gateway,
            now=found.clock,
        )
        await world.start()
        world.add(sent("s1", ASK), "message.sent")
        world.w.fake_gateway.answer(expects(QUESTION))
        await world.run()
        world.clock.advance(days=4)
        await world.run()
        message = world.w.service.messages[(ACCOUNT, "s1")]
        message["keywords"] = [k.upper() for k in message["keywords"]]
        world.w.service.change("message.updated", "s1")
        world.clock.advance(days=1)
        await world.run()

        assert world.item("s1").is_open
        assert message["keywords"] == ["AWAITING-REPLY"]
        assert len(world.w.store.actions(ref("s1"))) == 1


async def test_a_reply_in_the_thread_closes_it_and_takes_the_keyword_off(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    await world.run()
    assert world.keywords("s1") == ["agent-awaiting-reply"]

    world.add(received("r1", date="2026-11-20T10:00:00+00:00"))
    await world.run()

    assert (world.item("s1").is_open, world.item("s1").reason) == (False, "replied")
    assert world.keywords("s1") == []


async def test_an_automatic_answer_does_not_close_it(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()

    world.add(received("a1", subject="Automatische Antwort: Angebot"))
    await world.run()

    assert world.item("s1").is_open


async def test_writing_again_with_a_question_moves_the_item(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.add(
        sent(
            "s2",
            "Haben Sie meine Frage gesehen? Bitte kurz melden.",
            date="2026-11-18T09:00:00+00:00",
        ),
        "message.sent",
    )
    world.w.fake_gateway.answer(
        expects(QUESTION), expects("Haben Sie meine Frage gesehen?")
    )

    await world.run()

    assert (world.item("s1").is_open, world.item("s1").reason) == (False, "followed_up")
    assert world.item("s2").due == datetime(2026, 11, 23, 9, tzinfo=UTC)


async def test_writing_again_without_a_question_restarts_the_deadline(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.add(
        sent(
            "s2",
            "Noch eine Ergänzung zum Umfang anbei.",
            date="2026-11-18T09:00:00+00:00",
        ),
        "message.sent",
    )
    world.w.fake_gateway.answer(
        expects(QUESTION), no_reply("Noch eine Ergänzung zum Umfang anbei.")
    )

    await world.run()

    assert world.item("s1").is_open
    assert world.item("s1").due == datetime(2026, 11, 23, 9, tzinfo=UTC)
    assert world.item("s2") is None


async def test_a_keyword_taken_off_by_a_person_closes_it(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    await world.run()

    world.w.service.messages[(ACCOUNT, "s1")]["keywords"] = []
    world.w.service.change("message.updated", "s1")
    await world.run()

    assert (world.item("s1").is_open, world.item("s1").reason) == (
        False,
        "keyword_removed",
    )


async def test_its_own_keyword_does_not_close_it(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.clock.advance(days=4)
    await world.run()

    world.w.service.change("message.updated", "s1")
    await world.run()

    assert world.item("s1").is_open


async def test_shadow_records_the_keyword_and_sets_none(tmp_path: Path) -> None:
    async with wired(tmp_path) as found:
        world = World(found, stage="shadow")
        await world.start()
        world.add(sent("s1", ASK), "message.sent")
        world.w.fake_gateway.answer(expects(QUESTION))
        await world.run()
        world.clock.advance(days=4)
        await world.run()

        assert world.keywords("s1") == []
        assert [(a.action, a.executed) for a in found.store.actions()] == [
            ("add_keyword", False)
        ]


# -- the known misses, counted rather than argued away ------------------------------


async def test_known_miss_an_answer_outside_the_thread_closes_nothing(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()

    world.add(received("r1", subject="Angebot anbei", thread="t-new"))
    await world.run()

    assert world.item("s1").is_open


async def test_known_miss_an_answer_by_telephone_closes_nothing(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()

    world.clock.advance(days=4)
    await world.run()

    assert world.keywords("s1") == ["agent-awaiting-reply"]


async def test_known_miss_one_of_several_recipients_closes_it(world: World) -> None:
    world.add(sent("s1", ASK, to="team@partner.example"), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()

    world.add(received("r1", sender="one@partner.example"))
    await world.run()

    assert world.item("s1").reason == "replied"


# -- what it passes over -------------------------------------------------------------


async def test_a_message_outside_inbox_and_sent_is_skipped(world: World) -> None:
    world.add(wire_message("x1", folder_ids=["inv"], thread_id="t9"))

    await world.run()

    row = world.w.store.message(ref("x1"))
    assert row is not None and row.state == "skipped"


async def test_its_own_copy_in_the_inbox_closes_nothing(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()

    world.add(received("c1", sender=ME))
    await world.run()

    assert world.item("s1").is_open


def test_a_long_subject_cannot_blow_up_the_call() -> None:
    """A reply keeps the subject a stranger chose: it is cut, the same for
    the model and for the evidence check."""
    message = MailMessage(
        ref=ref("x"),
        to=(Address(email=PARTNER),),
        subject="S" * 20_000,
        text="T" * 20_000,
    )

    assert len(render(message)) < MAX_TEXT + MAX_SUBJECT + 200
    assert parts(message)[1:] == ["S" * MAX_SUBJECT, "T" * MAX_TEXT]


async def test_a_keyword_whose_removal_failed_is_taken_off_on_the_tick(
    world: World,
) -> None:
    await _due(world)
    assert world.keywords("s1") == ["agent-awaiting-reply"]
    world.w.service.write_refusal = (503, "unavailable")
    world.add(received("r1", date="2026-11-20T10:00:00+00:00"))
    await world.run()
    world.w.service.write_refusal = None

    for _ in range(2):
        world.clock.advance(days=1)
        await world.run()

    assert (world.item("s1").is_open, world.item("s1").reason) == (False, "replied")
    assert world.keywords("s1") == []
    assert not world.item("s1").keyword_set


async def test_an_item_closed_as_its_keyword_was_taken_off_asks_nothing(
    world: World,
) -> None:
    await _due(world)
    world.w.service.messages[(ACCOUNT, "s1")]["keywords"] = []
    world.w.service.change("message.updated", "s1")
    await world.run()
    assert world.item("s1").reason == "keyword_removed"
    asked = len(world.w.service.requests)

    world.clock.advance(days=1)
    await world.run()

    patches = [r for r in world.w.service.requests[asked:] if r.method == "PATCH"]
    assert patches == []


async def test_an_earlier_item_whose_message_is_gone_blocks_no_new_one(
    world: World,
) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    assert world.item("s1").is_open
    del world.w.service.messages[(ACCOUNT, "s1")]

    world.add(sent("s2", ASK, date="2026-11-17T09:00:00+00:00"), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()

    assert world.w.store.message(ref("s2")).state == "done"
    assert world.item("s2").is_open
    assert (world.item("s1").is_open, world.item("s1").reason) == (
        False,
        "message_gone",
    )


async def test_an_item_whose_message_went_to_the_trash_closes(world: World) -> None:
    world.add(sent("s1", ASK), "message.sent")
    world.w.fake_gateway.answer(expects(QUESTION))
    await world.run()
    world.w.service.messages[(ACCOUNT, "s1")]["folder_ids"] = ["trash"]
    world.w.service.change("message.updated", "s1")
    await world.run()

    assert (world.item("s1").is_open, world.item("s1").reason) == (False, "discarded")

    asked = len(world.w.service.requests)
    world.clock.advance(days=4)
    await world.run()
    patches = [r for r in world.w.service.requests[asked:] if r.method == "PATCH"]
    assert patches == []
