"""awaiting_reply: what closes an open item, in each stage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from benethos_mailbox_agents.agents.awaiting_reply.agent import AwaitingReply
from benethos_mailbox_agents.runtime.loop import Worker

from ..agents_fake import ACCOUNT
from ..agents_helpers import settings, wired
from .awaiting_reply_helpers import (
    ASK,
    QUESTION,
    World,
    bring_due,
    expects,
    no_reply,
    received,
    ref,
    sent,
    staged,
)

# -- what closes an item ------------------------------------------------------------


async def test_a_reply_to_a_sent_message_deleted_since_blocks_nothing(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    del awaiting_world.w.service.messages[(ACCOUNT, "s1")]

    awaiting_world.add(received("r1"))
    await awaiting_world.run()

    found = awaiting_world.w.store.message(ref("r1"))
    assert found is not None and found.state == "done"
    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "message_gone",
    )
    assert awaiting_world.w.store.cursor() == awaiting_world.w.service.state


async def test_a_gateway_that_is_away_holds_up_neither_tick_nor_replies(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    awaiting_world.add(sent("s2", ASK, thread="t2"), "message.sent")
    awaiting_world.add(sent("s3", ASK, thread="t3"), "message.sent")
    awaiting_world.add(received("r9", thread="t9"))
    awaiting_world.w.fake_gateway.answer(httpx.Response(503))

    await awaiting_world.run()

    assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]
    states = {m: awaiting_world.w.store.message(ref(m)) for m in ("s2", "s3", "r9")}
    assert {m: (row.state, row.attempts) for m, row in states.items() if row} == {
        "s2": ("pending", 0),
        "s3": ("pending", 0),
        "r9": ("done", 0),
    }
    assert len(awaiting_world.w.fake_gateway.requests) == 2


async def test_no_tick_while_a_message_waits_for_another_reason(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    awaiting_world.add(sent("s2", ASK, thread="t2"), "message.sent")
    awaiting_world.w.fake_gateway.answer(httpx.Response(503))
    await awaiting_world.run()
    assert awaiting_world.w.store.message(ref("s2")) is not None
    assert awaiting_world.worker._only_gateway_waits()

    # One due beyond the batch of this pass, such as a reply.
    awaiting_world.w.store.enqueue(ref("late"), awaiting_world.clock())

    assert not awaiting_world.worker._only_gateway_waits()


async def test_shadow_records_an_item_once_and_a_star_closes_nothing(
    tmp_path: Path,
) -> None:
    async for awaiting_world in staged(tmp_path, "shadow"):
        await bring_due(awaiting_world)
        assert awaiting_world.keywords("s1") == []
        assert [a.executed for a in awaiting_world.w.store.actions(ref("s1"))] == [
            False
        ]

        awaiting_world.w.service.change("message.updated", "s1")
        awaiting_world.clock.advance(days=1)
        await awaiting_world.run()

        assert awaiting_world.item("s1").is_open
        assert not awaiting_world.item("s1").keyword_set
        assert len(awaiting_world.w.store.actions(ref("s1"))) == 1


async def test_a_keyword_the_service_refused_is_offered_again(tmp_path: Path) -> None:
    async for awaiting_world in staged(tmp_path, "full"):
        awaiting_world.w.service.write_refusal = (422, "keyword_refused")
        await bring_due(awaiting_world)
        assert awaiting_world.keywords("s1") == []
        assert not awaiting_world.item("s1").keyword_set

        awaiting_world.w.service.write_refusal = None
        awaiting_world.clock.advance(days=1)
        await awaiting_world.run()

        assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]
        assert awaiting_world.item("s1").keyword_set


async def test_an_item_whose_sent_message_is_gone_closes_on_the_tick(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    del awaiting_world.w.service.messages[(ACCOUNT, "s1")]
    awaiting_world.clock.advance(days=4)

    await awaiting_world.run()

    found = awaiting_world.item("s1")
    assert found.closed is not None and found.reason == "message_gone"
    assert awaiting_world.w.store.due_items(awaiting_world.clock()) == []


async def test_after_shadow_the_keyword_stage_sets_the_keyword(tmp_path: Path) -> None:
    async for awaiting_world in staged(tmp_path, "shadow"):
        await bring_due(awaiting_world)
        assert awaiting_world.keywords("s1") == []

        moment = awaiting_world.clock.moment
        keyword = World(awaiting_world.w, "keyword")
        awaiting_world.clock.moment = moment
        awaiting_world.clock.advance(days=1)
        await keyword.run()

        assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]
        assert awaiting_world.item("s1").keyword_set


async def test_a_reply_decided_before_its_sent_message_opens_nothing(
    awaiting_world: World,
) -> None:
    awaiting_world.add(received("r1"), "")
    awaiting_world.add(sent("s1", ASK), "")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.worker.backfill(30)
    order = [row.ref.message_id for row in awaiting_world.w.store.messages("pending")]
    assert set(order) == {"r1", "s1"}

    await awaiting_world.worker.process_due()
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()

    assert awaiting_world.item("s1") is None
    assert awaiting_world.keywords("s1") == []


async def test_a_later_automatic_answer_still_opens_the_item(
    awaiting_world: World,
) -> None:
    awaiting_world.add(received("r1", sender="noreply@partner.example"), "")
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))

    await awaiting_world.run()

    assert awaiting_world.item("s1").is_open


async def test_taking_a_message_up_again_reopens_nothing(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()
    assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]
    awaiting_world.w.service.messages[(ACCOUNT, "s1")]["keywords"] = []
    awaiting_world.w.service.change("message.updated", "s1")
    await awaiting_world.run()
    assert awaiting_world.item("s1").reason == "keyword_removed"

    await awaiting_world.worker.backfill(30, again=True)
    awaiting_world.clock.advance(days=1)
    await awaiting_world.run()

    assert awaiting_world.item("s1").reason == "keyword_removed"
    assert awaiting_world.keywords("s1") == []


async def test_a_keyword_the_service_answers_in_another_case(tmp_path: Path) -> None:
    async with wired(tmp_path) as found:
        awaiting_world = World(found)
        awaiting_world.agent = AwaitingReply(
            settings(stage="full", reply_days=3, keyword="awaiting-reply")
        )
        awaiting_world.worker = Worker(
            agent=awaiting_world.agent,
            store=found.store,
            mailbox=found.mailbox,
            gateway=found.gateway,
            now=found.clock,
        )
        await awaiting_world.start()
        awaiting_world.add(sent("s1", ASK), "message.sent")
        awaiting_world.w.fake_gateway.answer(expects(QUESTION))
        await awaiting_world.run()
        awaiting_world.clock.advance(days=4)
        await awaiting_world.run()
        message = awaiting_world.w.service.messages[(ACCOUNT, "s1")]
        message["keywords"] = [k.upper() for k in message["keywords"]]
        awaiting_world.w.service.change("message.updated", "s1")
        awaiting_world.clock.advance(days=1)
        await awaiting_world.run()

        assert awaiting_world.item("s1").is_open
        assert message["keywords"] == ["AWAITING-REPLY"]
        assert len(awaiting_world.w.store.actions(ref("s1"))) == 1


async def test_a_reply_in_the_thread_closes_it_and_takes_the_keyword_off(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()
    assert awaiting_world.keywords("s1") == ["agent-awaiting-reply"]

    awaiting_world.add(received("r1", date="2026-11-20T10:00:00+00:00"))
    await awaiting_world.run()

    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "replied",
    )
    assert awaiting_world.keywords("s1") == []


async def test_an_automatic_answer_does_not_close_it(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()

    awaiting_world.add(received("a1", subject="Automatische Antwort: Angebot"))
    await awaiting_world.run()

    assert awaiting_world.item("s1").is_open


async def test_writing_again_with_a_question_moves_the_item(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.add(
        sent(
            "s2",
            "Haben Sie meine Frage gesehen? Bitte kurz melden.",
            date="2026-11-18T09:00:00+00:00",
        ),
        "message.sent",
    )
    awaiting_world.w.fake_gateway.answer(
        expects(QUESTION), expects("Haben Sie meine Frage gesehen?")
    )

    await awaiting_world.run()

    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "followed_up",
    )
    assert awaiting_world.item("s2").due == datetime(2026, 11, 23, 9, tzinfo=UTC)


async def test_writing_again_without_a_question_restarts_the_deadline(
    awaiting_world: World,
) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.add(
        sent(
            "s2",
            "Noch eine Ergänzung zum Umfang anbei.",
            date="2026-11-18T09:00:00+00:00",
        ),
        "message.sent",
    )
    awaiting_world.w.fake_gateway.answer(
        expects(QUESTION), no_reply("Noch eine Ergänzung zum Umfang anbei.")
    )

    await awaiting_world.run()

    assert awaiting_world.item("s1").is_open
    assert awaiting_world.item("s1").due == datetime(2026, 11, 23, 9, tzinfo=UTC)
    assert awaiting_world.item("s2") is None


async def test_a_keyword_taken_off_by_a_person_closes_it(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()

    awaiting_world.w.service.messages[(ACCOUNT, "s1")]["keywords"] = []
    awaiting_world.w.service.change("message.updated", "s1")
    await awaiting_world.run()

    assert (awaiting_world.item("s1").is_open, awaiting_world.item("s1").reason) == (
        False,
        "keyword_removed",
    )


async def test_its_own_keyword_does_not_close_it(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()

    awaiting_world.w.service.change("message.updated", "s1")
    await awaiting_world.run()

    assert awaiting_world.item("s1").is_open


async def test_shadow_records_the_keyword_and_sets_none(tmp_path: Path) -> None:
    async with wired(tmp_path) as found:
        awaiting_world = World(found, stage="shadow")
        await awaiting_world.start()
        awaiting_world.add(sent("s1", ASK), "message.sent")
        awaiting_world.w.fake_gateway.answer(expects(QUESTION))
        await awaiting_world.run()
        awaiting_world.clock.advance(days=4)
        await awaiting_world.run()

        assert awaiting_world.keywords("s1") == []
        assert [(a.action, a.executed) for a in found.store.actions()] == [
            ("add_keyword", False)
        ]
