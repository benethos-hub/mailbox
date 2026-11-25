"""The live check of invoices beside categorization, against the test
account of containers/live/mailbox-agents/. categorization WRITES to that
account, and the mail is put back.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/invoices.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

``invoices`` runs in ``shadow`` with the folders ``Providers/*`` and the
subfolder ``{folder}/Rechnungen``, beside ``categorization`` in ``full`` with the
list containers/live/mailbox-agents/categorization.json, in both orders:

1. ``invoices`` first: it marks the invoices in the inbox and opens an
   item for each. ``categorization`` then moves the mail of its groups, and the
   updates reach ``invoices`` through the feed, which records the move of
   each invoice into its subfolder, with no model call.
2. ``categorization`` first: the mail lies in the folders of the groups, and
   ``invoices`` finds it there through ``backfill``.

The mail goes back to where it was, and two checks of version 5 follow,
each with a state file of its own:

3. The end station: an invoice of the inbox is moved by hand into
   ``Invoices/Telco``, the inbox folder, which ``Invoices/*`` takes in.
   ``invoices`` records only the keyword for it, no folder and no move.
4. Marked mail under a state file made anew: an invoice of the inbox gets
   the keyword ``agent-invoice`` as from an earlier run. ``invoices`` skips
   it, with no step and no model call, and decides the others.

Then every message goes back to where it was, without either keyword.
``invoices`` asks the model of the settings, so the check costs one call
per message and run. Each check says ok or FAILED, and the exit code is 1
if one failed. Never point it at an account that is not a test account.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from email.utils import parseaddr
from pathlib import Path

from agents_common import (  # beside this script
    DAYS,
    LIST,
    Snapshot,
    categorization_keywords,
    connect_mailbox,
    inbox_snapshot,
    labels,
    mail,
    open_gateway,
    parse_settings,
    put_back,
    run_checks,
    sort_test_account,
    worker,
)

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.agents.categorization.lists import load_chain
from benethos_mailbox_agents.agents.invoices.agent import Invoices
from benethos_mailbox_agents.contract import Action
from benethos_mailbox_agents.llm.gateway import Gateway
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import Store

SUBFOLDER = "Rechnungen"
WAIT = 120
# The inbox folder of the checks of version 5, a folder of mail.py that
# Invoices/* takes in, and the invoices of the inbox they use.
END = "Invoices/Telco"
TO_END = "inv-telco-1"
MARKED = "inv-cloudhost-1"


def _invoices() -> tuple[int, set[str]]:
    """What the list and the labels make of the invented mail of mail.py:
    how many invoices lie in the inbox, and the subfolders of those that
    categorization moves. The invoice of a held group or of a sender in no group
    stays in the inbox."""
    # The first dimension of the list holds the moves by sender.
    partner = load_chain(LIST).chain.first
    count, filed = 0, set()
    for folder, _, message in mail.messages("me@invented.example"):
        gold = mail.GOLD.get(mail.local(str(message["Message-ID"])), {})
        label = gold.get("invoices", ("", {}))[0]
        if folder != "inbox" or label != "invoice":
            continue
        count += 1
        match = partner.match(parseaddr(str(message["From"]))[1])
        category = match.group if match else None
        if category is not None and not category.hold and category.target:
            filed.add(f"{category.target}/{SUBFOLDER}")
    return count, filed


INVOICES, FILED = _invoices()


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    gateway: Gateway
    folder: Path
    before: Snapshot = field(default_factory=dict)
    # Set once the mail is back, not before: a put back cut off half way
    # is done again on the way out.
    put_back_done: bool = False

    @property
    def keyword(self) -> str:
        """The keyword categorization sets with these settings."""
        return Categorization(self.settings).keyword

    @property
    def keywords(self) -> tuple[str, ...]:
        """Every keyword categorization sets with the list of the live setup."""
        return categorization_keywords(self.settings)

    def invoices(self, name: str, **values: object) -> tuple[Worker, Store]:
        settings = self.settings.model_copy(
            update={
                "stage": "shadow",
                "invoices_folders": ["Providers/*"],
                "invoices_subfolder": "{folder}/" + SUBFOLDER,
                "data_dir": self.folder,
                **values,
            }
        )
        agent = Invoices(settings)
        agent.prepare()
        store = Store.open(self.folder / f"invoices-{name}.db")
        return worker(agent, store, self.mailbox, self.gateway), store

    async def ref_of(self, local: str) -> MessageRef:
        """The message of the inbox whose Message-ID starts with ``local``,
        as mail.py names it."""
        for ref in self.before:
            message = await self.mailbox.message(ref)
            if mail.local(message.message_id_header) == local:
                return ref
        raise AssertionError(f"{local} is not in the inbox")

    @property
    def marked(self) -> str:
        """The keyword invoices sets with these settings."""
        return Invoices(self.settings).keyword

    async def restore(self) -> int:
        """Every message back as it lay, without the keyword of either
        agent where it had none."""
        return await put_back(self.mailbox, self.before, *self.keywords, self.marked)

    async def sort(self) -> None:
        await sort_test_account(self.settings, self.mailbox, "full", self.folder)


def recorded_moves(store: Store) -> set[str]:
    return {
        a.argument
        for a in store.actions()
        if a.action == Action.MOVE_TO_FOLDER.value and not a.executed
    }


async def by_header(live: Live, found: Snapshot) -> dict[str, MessageRef]:
    """The messages of ``found`` by their Message-ID. A message without
    one, or two with the same, end the check: the service may give a
    message a new id, and only its Message-ID tells it again."""
    headers = {
        ref: (await live.mailbox.message(ref)).message_id_header for ref in found
    }
    if any(not header for header in headers.values()):
        raise AssertionError("a message of the inbox has no Message-ID")
    twice = [h for h, n in Counter(headers.values()).items() if n > 1]
    if twice:
        raise AssertionError(f"{len(twice)} Message-IDs are in the inbox twice")
    return {str(header): ref for ref, header in headers.items()}


async def before(live: Live) -> str:
    live.before = await inbox_snapshot(live.mailbox, live.settings)
    return f"{len(live.before)} messages in the inbox"


async def invoices_first(live: Live) -> str:
    marking, store = live.invoices("first")
    with store:
        await marking.run_pass()
        await marking.backfill(DAYS)
        await marking.drain()
        decided = labels(store)["invoice"]
        if decided != INVOICES:
            raise AssertionError(f"{decided} invoices decided")
        opened = [i for i in (store.item(r) for r in live.before) if i and i.is_open]
        if len(opened) != INVOICES:
            raise AssertionError(f"{len(opened)} open items, {INVOICES} expected")
        steps = len(store.actions())
        await live.sort()
        started = time.monotonic()
        while recorded_moves(store) != FILED and time.monotonic() - started < WAIT:
            await asyncio.sleep(5)
            await marking.run_pass()
        found = recorded_moves(store)
        if found != FILED:
            raise AssertionError(
                f"recorded moves {sorted(found)}, {sorted(FILED)} expected"
            )
        filed = [
            i for i in (store.item(r) for r in live.before) if i and i.reason == "filed"
        ]
        calls = len(
            [s for r in live.before for s in store.steps(r) if s.step == "decision"]
        )
        if any(a.executed for a in store.actions()):
            raise AssertionError("invoices carried an action out in shadow")
        later = len(store.actions()) - steps
    return (
        f"{INVOICES} invoices marked, {len(filed)} filed after categorization "
        "moved them "
        f"({time.monotonic() - started:.0f} s through the feed), "
        f"{later} actions recorded then, {calls} decisions"
    )


async def categorization_first(live: Live) -> str:
    marking, store = live.invoices("second")
    with store:
        taken = await marking.backfill(DAYS)
        await marking.drain()
        found = recorded_moves(store)
        if found != FILED:
            raise AssertionError(
                f"recorded moves {sorted(found)}, {sorted(FILED)} expected"
            )
        decided = labels(store)["invoice"]
        made = sorted(
            {
                a.argument
                for a in store.actions()
                if a.action == Action.CREATE_FOLDER.value
            }
        )
    return f"{taken} taken up, {decided} invoices, folders recorded {made}"


async def put_back_between(live: Live) -> str:
    """The mail back, compared by Message-ID: the service may name a
    message moved by categorization and back under another id afterwards, which
    docs/mailbox-agents/concept/mailbox-service.md records. The checks after this one
    work on the inbox as it is then."""
    was = await by_header(live, live.before)
    moved = await live.restore()
    started = time.monotonic()
    while True:
        now = await inbox_snapshot(live.mailbox, live.settings)
        headers = await by_header(live, now)
        same = set(headers) == set(was) and all(
            now[headers[h]][1] == live.before[was[h]][1] for h in was
        )
        if same or time.monotonic() - started > WAIT:
            break
        await asyncio.sleep(5)
    if not same:
        missing = len(set(was) - set(headers))
        changed = sum(
            now[headers[h]][1] != live.before[was[h]][1] for h in was if h in headers
        )
        raise AssertionError(
            f"the inbox is not as it was: {missing} of {len(was)} not there, "
            f"{changed} with other keywords"
        )
    renewed = sum(headers[h] != was[h] for h in was)
    live.before = now
    return (
        f"{moved} messages back in the inbox, {renewed} of them under another "
        f"id ({time.monotonic() - started:.0f} s)"
    )


async def end_station(live: Live) -> str:
    ref = await live.ref_of(TO_END)
    end = await live.mailbox.folder_at(ref.account_id, END)
    if end is None:
        raise AssertionError(
            f"{END} is missing, run containers/live/mailbox-agents/setup.sh"
        )
    await live.mailbox.move(ref, end.id)
    marking, store = live.invoices(
        "end-station",
        invoices_folders=["Providers/*", "Invoices/*"],
        invoices_inbox_folder=END,
    )
    with store:
        await marking.backfill(DAYS)
        await marking.drain()
        decided = [s for s in store.steps(ref) if s.step == "decision"]
        if not decided or decided[-1].result["label"] != "invoice":
            raise AssertionError("the invoice in the end station was not decided")
        found = [(a.action, a.argument) for a in store.actions(ref)]
        if found != [(Action.ADD_KEYWORD.value, live.marked)]:
            raise AssertionError(f"recorded {found}, the keyword alone expected")
        made = [a for a in store.actions() if a.argument.startswith(END + "/")]
        if made:
            raise AssertionError("an action below the end station was recorded")
        folders = await live.mailbox.folders(ref.account_id, fresh=True)
        described = marking.agent.describe_folders(
            {f.path: f for f in folders.values()}
        )
    line = next(line for line in described if line.startswith(END + ":"))
    await put_back_between(live)
    return f"marked there and left, status says {line!r}, then put back"


async def marked_before(live: Live) -> str:
    ref = await live.ref_of(MARKED)
    await live.mailbox.add_keyword(ref, live.marked)
    marking, store = live.invoices("made-anew")
    with store:
        await marking.backfill(DAYS)
        await marking.drain()
        row = store.message(ref)
        if row is None or row.state != "skipped" or store.steps(ref):
            raise AssertionError("the marked invoice was not skipped")
        decided = labels(store)["invoice"]
        if decided != INVOICES - 1:
            raise AssertionError(f"{decided} invoices decided, {INVOICES - 1} expected")
    return f"skipped with no step, the other {decided} invoices decided"


async def put_back_check(live: Live) -> str:
    said = await put_back_between(live)
    live.put_back_done = True
    return said


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("the inbox before", before),
    ("invoices first, then categorization", invoices_first),
    ("categorization first, then invoices", categorization_first),
    ("the mail put back after categorization", put_back_between),
    ("an invoice put into the end station by hand", end_station),
    ("a marked invoice under a state file made anew", marked_before),
    ("the mail put back", put_back_check),
]


async def run(settings: Settings) -> int:
    async with AsyncExitStack() as stack:
        mailbox = await stack.enter_async_context(connect_mailbox(settings))
        gateway = await stack.enter_async_context(open_gateway(settings))
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        live = Live(settings, mailbox, gateway, folder)
        try:
            failed = await run_checks(live, CHECKS, stop=True)
        finally:
            # A check that failed or a run cut short leaves no mail moved.
            if not live.put_back_done:
                moved = await live.restore()
                if moved:
                    print(f"         {moved} messages back in the inbox")
    return 1 if failed else 0


if __name__ == "__main__":
    found = parse_settings("invoices", "The live check of invoices.")
    sys.exit(asyncio.run(run(found)))
