"""The live check of the actor filing, against the test account of
containers/live/mailbox-agents/. It WRITES to that account and puts the
mail back.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/filing.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

It sets the keywords a person or an instance of categorization would set,
a partner keyword and ``agent-invoice``, on the invoices of CloudHost and
Telco of the invented mail, and runs filing with the example list of
config/benethos-mailbox-agents/filing.example.json. In ``shadow`` it moves
nothing and records two moves. In ``full`` a backfill takes both up, each
is moved once into ``Providers/<partner>/Invoices`` and gets
``agent-filed``. One moved back into the inbox by hand, with a keyword
set anew, stays there. Then it moves every message back and takes every
keyword off. The folders made stay. Each check says ok or FAILED, and the
exit code is 1 if one failed. Never point it at an account that is not a
test account.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from agents_common import (  # beside this script
    DAYS,
    ROOT,
    Snapshot,
    connect_mailbox,
    inbox_snapshot,
    parse_settings,
    put_back,
    run_checks,
    snapshot,
    worker,
)

from benethos_mailbox_agents.agents.filing.agent import Filing
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import Store

LIST = ROOT / "config" / "benethos-mailbox-agents" / "filing.example.json"
# The invoices of the invented mail by the local part of their Message-ID,
# each with its partner.
INVOICES = {"inv-cloudhost-1": "cloudhost", "inv-telco-1": "telco"}
TARGETS = {
    "cloudhost": "Providers/CloudHost/Invoices",
    "telco": "Providers/Telco/Invoices",
}
OWN = "agent-filed"
# How long the feed may take to name a change: measured about 9 seconds.
SETTLE_SECONDS = 120


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    folder: Path
    stack: ExitStack
    before: Snapshot = field(default_factory=dict)
    invoices: dict[MessageRef, str] = field(default_factory=dict)
    inbox: str = ""
    full: Worker | None = None
    put_back_done: bool = False

    def filing(self, stage: str, name: str) -> Worker:
        """A worker of filing in ``stage``, with a state file of its own."""
        found = self.settings.model_copy(
            update={"stage": stage, "filing_file": LIST, "data_dir": self.folder}
        )
        agent = Filing(found)
        agent.prepare()
        store = self.stack.enter_context(Store.open(self.folder / f"{name}.db"))
        return worker(agent, store, self.mailbox)

    async def settle(
        self, running: Worker, done: Callable[[], Awaitable[bool]]
    ) -> None:
        """Passes of ``running`` until ``done`` says so: the feed names a
        change some seconds later."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        while loop.time() - started < SETTLE_SECONDS:
            await running.run_pass()
            if await done():
                return
            await asyncio.sleep(6)
        raise AssertionError(f"nothing settled in {SETTLE_SECONDS} seconds")

    async def paths(self, ref: MessageRef) -> list[str]:
        message = await self.mailbox.message(ref)
        return [folder.path for folder in message.folders]

    async def in_inbox(self, ref: MessageRef) -> bool:
        message = await self.mailbox.message(ref)
        return [folder.id for folder in message.folders] == [self.inbox]


def keywords(partner: str) -> tuple[str, str]:
    return f"agent-partner-{partner}", "agent-invoice"


async def before(live: Live) -> str:
    live.before = await inbox_snapshot(live.mailbox, live.settings)
    for ref in live.before:
        message = await live.mailbox.message(ref)
        local = (message.message_id_header or "").strip("<>").split("@")[0]
        if local in INVOICES:
            live.invoices[ref] = INVOICES[local]
            live.inbox = next(f.id for f in message.folders if f.role == "inbox")
    if sorted(live.invoices.values()) != sorted(INVOICES.values()):
        raise AssertionError("the invoices of CloudHost and Telco are not in the inbox")
    return f"{len(live.before)} messages in the inbox, the two invoices among them"


async def shadow(live: Live) -> str:
    running = live.filing("shadow", "shadow")
    await running.run_pass()
    for ref, partner in live.invoices.items():
        for keyword in keywords(partner):
            await live.mailbox.add_keyword(ref, keyword)

    def recorded() -> list[str]:
        return [
            a.argument
            for a in running.store.actions()
            if a.action == "move_to_folder" and not a.executed
        ]

    async def done() -> bool:
        return len(recorded()) == len(live.invoices)

    await live.settle(running, done)
    for ref in live.invoices:
        if not await live.in_inbox(ref):
            raise AssertionError("shadow moved a message")
    moved = [a for a in running.store.actions() if a.executed]
    if moved:
        raise AssertionError(f"shadow carried out {len(moved)} actions")
    return f"nothing moved, moves recorded to {sorted(recorded())}"


async def full(live: Live) -> str:
    running = live.filing("full", "full")
    await running.backfill(DAYS)
    await running.drain()
    for ref, partner in live.invoices.items():
        if await live.paths(ref) != [TARGETS[partner]]:
            raise AssertionError(f"the invoice of {partner} is not in its folder")
        message = await live.mailbox.message(ref)
        if OWN not in message.keywords:
            raise AssertionError(f"the invoice of {partner} lacks {OWN}")
    moves = [
        a
        for a in running.store.actions()
        if a.action == "move_to_folder" and a.executed
    ]
    if len(moves) != len(live.invoices):
        raise AssertionError(f"{len(moves)} moves, {len(live.invoices)} expected")
    live.full = running
    return f"each moved once, into {sorted(TARGETS.values())}, {OWN} set"


async def by_hand(live: Live) -> str:
    """One invoice put back into the inbox by a person, its keyword set
    anew: it stays where it was put."""
    running = live.full
    if running is None:
        raise AssertionError("filing in full did not run")
    ref = next(iter(live.invoices))
    await live.mailbox.move(ref, live.inbox)
    await live.mailbox.remove_keyword(ref, "agent-invoice")
    await live.mailbox.add_keyword(ref, "agent-invoice")
    for _ in range(4):
        await running.run_pass()
        await asyncio.sleep(6)
    if not await live.in_inbox(ref):
        raise AssertionError("the message put back by hand was moved again")
    return "it stays in the inbox"


async def put_back_check(live: Live) -> str:
    taken = (OWN, "agent-invoice", *(f"agent-partner-{p}" for p in INVOICES.values()))
    moved = await put_back(live.mailbox, live.before, *taken)
    live.put_back_done = True
    after = await snapshot(live.mailbox, live.before)
    if after != live.before:
        changed = sum(after.get(ref) != was for ref, was in live.before.items())
        raise AssertionError(f"{changed} messages are not as they were")
    return f"{moved} messages back in the inbox, keywords off"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("the inbox before", before),
    ("filing in shadow", shadow),
    ("filing in full", full),
    ("a message put back by hand", by_hand),
    ("the mail put back", put_back_check),
]


async def run(settings: Settings) -> int:
    async with connect_mailbox(settings) as mailbox:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            live = Live(settings, mailbox, Path(folder), stack)
            try:
                failed = await run_checks(live, CHECKS, stop=True)
            finally:
                if not live.put_back_done and live.before:
                    await put_back_check(live)
    return 1 if failed else 0


if __name__ == "__main__":
    found = parse_settings("filing", "The live check of the actor filing.")
    sys.exit(asyncio.run(run(found)))
