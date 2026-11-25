"""The live check of three instances of the agent sorting that hand a
message on by keywords, against the test account of
containers/live/mailbox-agents/. It WRITES to that account and puts the
mail back.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/chain.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

It runs the example lists of containers/live/mailbox-agents/chain/, each
instance with a state file of its own: ``partner`` in ``keyword`` over the
inbox of the last weeks, which sets a keyword per partner and its sign,
``beleg`` in ``keyword``, which asks the model of the settings whether
each message is an invoice and sets ``agent-invoice`` and its sign, and
``ablage`` in ``full``, which waits for the sign of ``beleg`` in the feed
and moves the mail of a partner, an invoice below it into ``Rechnungen``.
Then a partner keyword set by hand on the invoice of a sender in no group
reaches ``beleg`` without a new model call and ``ablage`` moves it once,
and a second correction moves nothing. Then it moves every message back
and takes every keyword off. The folders made stay. Each check says ok or
FAILED, and the exit code is 1 if one failed. Never point it at an
account that is not a test account.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path

from agents_common import (  # beside this script
    DAYS,
    LIVE,
    Snapshot,
    connect_mailbox,
    inbox_snapshot,
    mail,
    open_gateway,
    parse_settings,
    put_back,
    run_checks,
    snapshot,
    worker,
)

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import Store

LISTS = LIVE / "chain"
# Each instance, its stage, and whether it asks the model.
INSTANCES = (("partner", "keyword"), ("beleg", "keyword"), ("ablage", "full"))
# The partners of the example list, by sender.
PARTNERS = {
    "billing@cloudhost.example": "cloudhost",
    "rechnung@telco.example": "telco",
}
# How long the feed may take to name a change: measured about 9 seconds.
SETTLE_SECONDS = 120


def _gold() -> tuple[set[str], str]:
    """The senders of the invoices of mail.py in the inbox, and the one of
    them in no group of the example list."""
    senders = set()
    for folder, _, message in mail.messages("me@invented.example"):
        labels = mail.GOLD.get(mail.local(str(message["Message-ID"])), {})
        if folder == "inbox" and labels.get("invoices", ("",))[0] == "invoice":
            senders.add(parseaddr(str(message["From"]))[1])
    stranger = sorted(s for s in senders if s not in PARTNERS and "paperworks" not in s)
    return senders, stranger[0]


INVOICE_SENDERS, STRANGER = _gold()


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    folder: Path
    stack: ExitStack
    gateway_stack: AsyncExitStack
    workers: dict[str, Worker] = field(default_factory=dict)
    before: Snapshot = field(default_factory=dict)
    senders: dict[MessageRef, str] = field(default_factory=dict)
    calls_after_beleg: int = 0
    put_back_done: bool = False

    @property
    def keywords(self) -> tuple[str, ...]:
        found: set[str] = set()
        for one in self.workers.values():
            found |= one.agent.keywords()
        return tuple(sorted(found))

    async def start(self) -> None:
        """A worker for each instance, the feed started at now."""
        for name, stage in INSTANCES:
            found = self.settings.model_copy(
                update={
                    "stage": stage,
                    "instance": name,
                    "sorting_file": LISTS / f"sorting.{name}.example.json",
                    "data_dir": self.folder,
                }
            )
            agent = Sorting(found)
            agent.prepare()
            gateway = None
            if agent.asks_model():
                gateway = await self.gateway_stack.enter_async_context(
                    open_gateway(found)
                )
            store = self.stack.enter_context(Store.open(self.folder / f"{name}.db"))
            self.workers[name] = worker(agent, store, self.mailbox, gateway)
            await self.workers[name].run_pass()

    async def settle(self, *names: str) -> None:
        """Passes of the instances ``names`` until the inbox stands still
        for two rounds: the feed names a change some seconds later."""
        started, still, last = asyncio.get_running_loop().time(), 0, None
        while asyncio.get_running_loop().time() - started < SETTLE_SECONDS:
            for name in names:
                await self.workers[name].run_pass()
            now = await snapshot(self.mailbox, self.before)
            still = still + 1 if now == last else 0
            if still >= 2:
                return
            last = now
            await asyncio.sleep(6)

    def calls(self) -> int:
        store = self.workers["beleg"].store
        return store.model_calls_since(datetime(2000, 1, 1, tzinfo=UTC))

    async def keywords_of(self, sender: str) -> list[set[str]]:
        refs = [ref for ref, found in self.senders.items() if found == sender]
        now = await snapshot(self.mailbox, refs)
        return [set(keywords) for _, keywords in now.values()]


async def before(live: Live) -> str:
    live.before = await inbox_snapshot(live.mailbox, live.settings)
    for ref in live.before:
        message = await live.mailbox.message(ref)
        live.senders[ref] = message.sender.email.lower() if message.sender else ""
    await live.start()
    return f"{len(live.before)} messages in the inbox, three instances started"


async def partner(live: Live) -> str:
    await live.workers["partner"].backfill(DAYS)
    await live.workers["partner"].drain()
    for sender, name in PARTNERS.items():
        for keywords in await live.keywords_of(sender):
            wanted = {f"agent-partner-{name}", "agent-sorted-partner"}
            if not wanted <= keywords:
                raise AssertionError(f"a message of {name} lacks its keywords")
    return f"partner keywords on the mail of {len(PARTNERS)} partners"


async def beleg(live: Live) -> str:
    await live.workers["beleg"].backfill(DAYS)
    await live.workers["beleg"].drain()
    await live.settle("beleg")
    marked = 0
    for sender in INVOICE_SENDERS:
        for keywords in await live.keywords_of(sender):
            marked += "agent-invoice" in keywords
    stranger = await live.keywords_of(STRANGER)
    if not any("agent-invoice" in k for k in stranger):
        raise AssertionError("the invoice of a sender in no group lacks agent-invoice")
    live.calls_after_beleg = live.calls()
    return (
        f"{marked} messages of the gold invoice senders marked, the invoice of a "
        f"sender in no group among them, {live.calls_after_beleg} model calls"
    )


async def ablage(live: Live) -> str:
    await live.settle("beleg", "ablage")
    moved = [
        a
        for a in live.workers["ablage"].store.actions()
        if a.action == "move_to_folder" and a.executed
    ]
    targets = sorted({a.argument for a in moved})
    wanted = {"Providers/CloudHost/Rechnungen", "Providers/Telco/Rechnungen"}
    if not wanted <= set(targets):
        raise AssertionError(
            f"moved to {targets}, {sorted(wanted)} expected among them"
        )
    if len(moved) != len({a.ref for a in moved}):
        raise AssertionError("a message was moved twice")
    return f"{len(moved)} moved, into {targets}"


async def by_hand(live: Live) -> str:
    """A partner keyword set by hand on the invoice of a stranger, then
    corrected again."""
    ref = next(r for r, s in live.senders.items() if s == STRANGER)
    await live.mailbox.add_keyword(ref, "agent-partner-telco")
    await live.settle("beleg", "ablage")
    message = await live.mailbox.message(ref)
    if [f.path for f in message.folders] != ["Providers/Telco/Rechnungen"]:
        raise AssertionError("the corrected invoice was not filed below Telco")
    await live.mailbox.remove_keyword(ref, "agent-partner-telco")
    await live.mailbox.add_keyword(ref, "agent-partner-cloudhost")
    await live.settle("beleg", "ablage")
    message = await live.mailbox.message(ref)
    if [f.path for f in message.folders] != ["Providers/Telco/Rechnungen"]:
        raise AssertionError("a second correction moved the message again")
    if live.calls() != live.calls_after_beleg:
        raise AssertionError("a correction asked the model again")
    return "filed below Telco once, the second correction moved nothing, no call"


async def put_back_check(live: Live) -> str:
    keywords = (*live.keywords, "agent-partner-cloudhost", "agent-partner-telco")
    moved = await put_back(live.mailbox, live.before, *keywords)
    live.put_back_done = True
    after = await snapshot(live.mailbox, live.before)
    if after != live.before:
        changed = sum(after.get(ref) != was for ref, was in live.before.items())
        raise AssertionError(f"{changed} messages are not as they were")
    return f"{moved} messages back in the inbox, keywords off"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("the inbox before", before),
    ("partner in keyword", partner),
    ("beleg in keyword", beleg),
    ("ablage in full", ablage),
    ("a partner corrected by hand", by_hand),
    ("the mail put back", put_back_check),
]


async def run(settings: Settings) -> int:
    async with connect_mailbox(settings) as mailbox, AsyncExitStack() as gateways:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            live = Live(settings, mailbox, Path(folder), stack, gateways)
            try:
                failed = await run_checks(live, CHECKS, stop=True)
            finally:
                if not live.put_back_done and live.before:
                    keywords = (
                        *live.keywords,
                        "agent-partner-cloudhost",
                        "agent-partner-telco",
                    )
                    moved = await put_back(live.mailbox, live.before, *keywords)
                    if moved:
                        print(f"         {moved} messages back in the inbox")
    return 1 if failed else 0


if __name__ == "__main__":
    found = parse_settings("chain", "The live check of three instances of sorting.")
    sys.exit(asyncio.run(run(found)))
