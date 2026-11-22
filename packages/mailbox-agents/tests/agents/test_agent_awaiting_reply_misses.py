"""awaiting_reply: the known misses, counted rather than argued away,
and what it passes over."""

from __future__ import annotations

from benethos_mailbox_agents.agents.awaiting_reply.schema import (
    MAX_SUBJECT,
    MAX_TEXT,
    parts,
    render,
)
from benethos_mailbox_agents.records import Address, MailMessage

from ..agents_fake import ACCOUNT, wire_message
from .awaiting_reply_helpers import (
    ASK,
    ME,
    PARTNER,
    QUESTION,
    World,
    bring_due,
    expects,
    received,
    ref,
    sent,
)

# -- the known misses, counted rather than argued away ------------------------------


async def test_known_miss_an_answer_outside_the_thread_closes_nothing(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()

    awaiting_world.add(received("r1", subject="Angebot anbei", thread="t-new"))
    await awaiting_world.run()

    assert awaiting_world.item("s1").is_open


async def test_known_miss_an_answer_by_telephone_closes_nothing(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()

    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()

    assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]


async def test_known_miss_one_of_several_recipients_closes_it(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK, to="team@partner.example"), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()

    awaiting_world.add(received("r1", sender="one@partner.example"))
    await awaiting_world.run()

    assert awaiting_world.item("s1").reason == "replied"


# -- what it passes over -------------------------------------------------------------


async def test_a_message_outside_inbox_and_sent_is_skipped(
    awaiting_world: World,
) -> None:
    awaiting_world.add(wire_message("x1", folder_ids=["inv"], thread_id="t9"))

    await awaiting_world.run()

    row = awaiting_world.w.store.message(ref("x1"))
    assert row is not None and row.state == "skipped"


async def test_its_own_copy_in_the_inbox_closes_nothing(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()

    awaiting_world.add(received("c1", sender=ME))
    await awaiting_world.run()

    assert awaiting_world.item("s1").is_open


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
    awaiting_world: World,
) -> None:
    await bring_due(awaiting_world)
    assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]
    awaiting_world.w.service.write_refusal = (503, "unavailable")
    awaiting_world.add(received("r1", date="2026-11-20T10:00:00+00:00"))
    await awaiting_world.run()
    awaiting_world.w.service.write_refusal = None

    for _ in range(2):
        awaiting_world.clock.advance(days=1)
        await awaiting_world.run()

    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "replied",
    )
    assert awaiting_world.keywords("s1") == []
    assert not awaiting_world.item("s1").keyword_set


async def test_an_item_closed_as_its_keyword_was_taken_off_asks_nothing(
    awaiting_world: World,
) -> None:
    await bring_due(awaiting_world)
    awaiting_world.w.service.messages[(ACCOUNT, "s1")]["keywords"] = []
    awaiting_world.w.service.change("message.updated", "s1")
    await awaiting_world.run()
    assert awaiting_world.item("s1").reason == "keyword_removed"
    asked = len(awaiting_world.w.service.requests)

    awaiting_world.clock.advance(days=1)
    await awaiting_world.run()

    patches = [
        r for r in awaiting_world.w.service.requests[asked:] if r.method == "PATCH"
    ]
    assert patches == []


async def test_an_earlier_item_whose_message_is_gone_blocks_no_new_one(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    assert awaiting_world.item("s1").is_open
    del awaiting_world.w.service.messages[(ACCOUNT, "s1")]

    awaiting_world.add(
        sent("s2", ASK, date="2026-11-17T09:00:00+00:00"), "message.sent"
    )
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()

    assert awaiting_world.w.store.message(ref("s2")).state == "done"
    assert awaiting_world.item("s2").is_open
    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "message_gone",
    )


async def test_an_item_whose_message_went_to_the_trash_closes(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.w.service.messages[(ACCOUNT, "s1")]["folder_ids"] = ["trash"]
    awaiting_world.w.service.change("message.updated", "s1")
    await awaiting_world.run()

    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "discarded",
    )

    asked = len(awaiting_world.w.service.requests)
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()
    patches = [
        r for r in awaiting_world.w.service.requests[asked:] if r.method == "PATCH"
    ]
    assert patches == []


def _asked_for(awaiting_world: World, message_id: str, since: int) -> list[str]:
    """The requests about ``message_id`` from the ``since``-th on."""
    return [
        r.method
        for r in awaiting_world.w.service.requests[since:]
        if r.url.path.endswith(f"/{message_id}")
    ]


async def _replied_with_the_keyword_noted(awaiting_world: World) -> None:
    """An item closed by a reply, its keyword taken off by the step and
    still noted as set until the tick sees it gone."""
    await bring_due(awaiting_world)
    awaiting_world.add(received("r1", date="2026-11-20T10:00:00+00:00"))
    await awaiting_world.run()
    assert awaiting_world.item("s1").reason == "replied"
    assert awaiting_world.item("s1").keyword_set


async def test_a_closed_item_whose_message_went_to_the_trash_is_asked_no_more(
    awaiting_world: World,
) -> None:
    await _replied_with_the_keyword_noted(awaiting_world)
    awaiting_world.w.service.messages[(ACCOUNT, "s1")]["folder_ids"] = ["trash"]

    awaiting_world.clock.advance(days=1)
    await awaiting_world.run()
    assert not awaiting_world.item("s1").keyword_set
    asked = len(awaiting_world.w.service.requests)
    for _ in range(2):
        awaiting_world.clock.advance(days=1)
        await awaiting_world.run()

    assert _asked_for(awaiting_world, "s1", asked) == []
    assert awaiting_world.item("s1").reason == "replied"


async def test_a_closed_item_whose_message_is_deleted_is_asked_no_more(
    awaiting_world: World,
) -> None:
    await _replied_with_the_keyword_noted(awaiting_world)
    del awaiting_world.w.service.messages[(ACCOUNT, "s1")]

    awaiting_world.clock.advance(days=1)
    await awaiting_world.run()
    assert not awaiting_world.item("s1").keyword_set
    asked = len(awaiting_world.w.service.requests)
    for _ in range(2):
        awaiting_world.clock.advance(days=1)
        await awaiting_world.run()

    assert _asked_for(awaiting_world, "s1", asked) == []
    assert awaiting_world.item("s1").reason == "replied"


async def test_an_item_due_in_the_trash_closes_as_discarded_on_the_tick(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    # Moved without an update the agent saw, as after a feed that expired.
    awaiting_world.w.service.messages[(ACCOUNT, "s1")]["folder_ids"] = ["trash"]

    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()
    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "discarded",
    )
    asked = len(awaiting_world.w.service.requests)
    awaiting_world.clock.advance(days=1)
    await awaiting_world.run()

    assert _asked_for(awaiting_world, "s1", asked) == []
