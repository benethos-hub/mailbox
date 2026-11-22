"""What the tests of awaiting_reply share: the two people, mail sent and
received, the model's two answers, and the world of one test."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benethos_mailbox_agents.agents.awaiting_reply.agent import AwaitingReply
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Wired, settings, wired
from ..clocks import Clock

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


async def staged(tmp_path: Path, stage: str) -> AsyncIterator[World]:
    async with wired(tmp_path) as found:
        made = World(found, stage)
        await made.start()
        yield made


async def bring_due(awaiting_world: World) -> None:
    awaiting_world.add(sent("s1", ASK), "message.sent")
    awaiting_world.w.fake_gateway.answer(expects(QUESTION))
    await awaiting_world.run()
    awaiting_world.clock.advance(days=4)
    await awaiting_world.run()
