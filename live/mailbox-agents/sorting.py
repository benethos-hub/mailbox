"""The live check of the agent sorting, against the test account of
containers/live/mailbox-agents/. It WRITES to that account and puts the mail back.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/sorting.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

It runs ``sorting`` over the mail of the last weeks with the list
containers/live/mailbox-agents/sorting.json, each time with a state file in a folder of
its own: first in ``shadow``, which must change nothing in the mailbox,
then in ``full``, which makes the missing folders and moves the mail of
each group not held, with the agent's keyword, and sets the keyword of
the second dimension of the list on the mail of two groups. Then it
moves every message back to where it was and takes the keywords off. The folders it
made stay: no agent may delete a folder, and a second run finds them
there. Each check says ok or FAILED, and the exit code is 1 if one
failed. Never point it at an account that is not a test account.

The list has groups with a topic, so each run asks the model of the
settings once for every message no sender rule settles. The moves by a
sender rule are code and checked exactly. What the model chooses is
not: in ``full`` a message may move by its topic only into the folder
of the group that acts on it, never into that of a group that records
it, and the check says how many it moved against the gold labels of
mail.py. How well the model chooses is measured by ``eval``.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from agents_common import (  # beside this script
    Snapshot,
    connect_mailbox,
    inbox_snapshot,
    mail,
    parse_settings,
    put_back,
    run_checks,
    snapshot,
    sort_test_account,
    sorting_keywords,
)

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.contract import Action
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import ActionRow

# What the sender rules of the list make of the invented mail of
# containers/live/mailbox-agents/mail.py.
MOVED = {"CloudHost": 3, "Telco": 1}
HELD = {"Paperworks": 2}
# The keyword of the second dimension of the list, by sender alone after
# the first, and how many of the moved messages carry it: those of
# CloudHost and Telco.
BILLING = ("agent-billing", 4)
FOLDERS = ("Providers", "Providers/CloudHost", "Providers/Telco")
# The groups chosen by their topic: the one that acts and its folder, and
# the folders of those that record it, never made.
ACTS = ("Project Harbor", "Projects/Harbor")
RECORDS = ("Projects/Lighthouse", "Applications")
# How many messages of mail.py belong to the group that acts.
TO_ACT = sum(
    1 for labels in mail.GOLD.values() if labels.get("sorting", ("",))[0] == ACTS[0]
)


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    before: Snapshot = field(default_factory=dict)
    folders_before: set[str] = field(default_factory=set)
    moved: list[ActionRow] = field(default_factory=list)
    # Set once the mail is back, not before: a put back cut off half way
    # is done again on the way out.
    put_back_done: bool = False

    @property
    def account(self) -> str:
        return self.settings.accounts[0]

    @property
    def keyword(self) -> str:
        """The keyword sorting sets with these settings."""
        return Sorting(self.settings).keyword

    @property
    def keywords(self) -> tuple[str, ...]:
        """Every keyword sorting sets with the list of the live setup."""
        return sorting_keywords(self.settings)

    async def sort(
        self, stage: str, folder: Path
    ) -> tuple[list[ActionRow], Counter[str]]:
        return await sort_test_account(self.settings, self.mailbox, stage, folder)

    async def folders(self) -> set[str]:
        found = await self.mailbox.folders(self.account, fresh=True)
        return {f.path for f in found.values()}


async def before(live: Live) -> str:
    live.before = await inbox_snapshot(live.mailbox, live.settings)
    live.folders_before = await live.folders()
    return f"{len(live.before)} messages in the inbox"


async def shadow(live: Live) -> str:
    with tempfile.TemporaryDirectory() as folder:
        actions, labels = await live.sort("shadow", Path(folder))
    for name, count in {**MOVED, **HELD}.items():
        if labels[name] != count:
            raise AssertionError(f"{labels[name]} messages of {name}, {count} expected")
    by_topic = {
        name: count
        for name, count in labels.items()
        if name not in MOVED and name not in HELD and name != "none"
    }
    if any(a.executed for a in actions):
        raise AssertionError("an action was carried out in shadow")
    after = await inbox_snapshot(live.mailbox, live.settings)
    if after != live.before or await live.folders() != live.folders_before:
        raise AssertionError("the mailbox changed in shadow")
    moves = sum(a.action == Action.MOVE_TO_FOLDER.value for a in actions)
    made = sorted(
        {a.argument for a in actions if a.action == Action.CREATE_FOLDER.value}
    )
    return (
        f"{sum(labels.values())} decided, by topic {by_topic or 'none'}, "
        f"{moves} moves and the folders {made or 'none'} recorded, nothing changed"
    )


async def full(live: Live) -> str:
    with tempfile.TemporaryDirectory() as folder:
        actions, _ = await live.sort("full", Path(folder))
    live.moved = [
        a for a in actions if a.action == Action.MOVE_TO_FOLDER.value and a.executed
    ]
    folders = await live.folders()
    missing = [path for path in FOLDERS if path not in folders]
    if missing:
        raise AssertionError(f"the folders {missing} were not made")
    if "Paperworks" in folders - live.folders_before:
        raise AssertionError("the folder of a held group was made")
    recorded = sorted(set(RECORDS) & (folders - live.folders_before))
    if recorded:
        raise AssertionError(
            f"the folders {recorded} of a group that records were made"
        )
    by_folder = Counter(a.argument for a in live.moved)
    by_topic = by_folder.pop(ACTS[1], 0)
    expected = {f"Providers/{name}": count for name, count in MOVED.items()}
    if dict(by_folder) != expected:
        raise AssertionError(f"moved {dict(by_folder)}, {expected} expected")
    billed = 0
    for action in live.moved:
        message = await live.mailbox.message(action.ref)
        if [f.path for f in message.folders] != [action.argument]:
            raise AssertionError("a message is not in the folder it was moved to")
        if live.keyword.casefold() not in {k.casefold() for k in message.keywords}:
            raise AssertionError("a moved message lacks the keyword")
        if BILLING[0] in {k.casefold() for k in message.keywords}:
            billed += 1
    if billed != BILLING[1]:
        raise AssertionError(
            f"{billed} messages with {BILLING[0]}, {BILLING[1]} expected"
        )
    made = sorted((folders - live.folders_before) & {*FOLDERS, "Projects", ACTS[1]})
    return (
        f"{sum(by_folder.values())} moved by sender, {by_topic} by topic into "
        f"{ACTS[1]} ({TO_ACT} by the gold labels), {sum(HELD.values())} held, "
        f"{billed} with {BILLING[0]}, "
        f"folders made {made or 'none, there from an earlier run'}"
    )


async def put_back_check(live: Live) -> str:
    moved = await put_back(live.mailbox, live.before, *live.keywords)
    live.put_back_done = True
    after = await snapshot(live.mailbox, live.before)
    if after != live.before:
        changed = sum(after.get(ref) != was for ref, was in live.before.items())
        raise AssertionError(f"{changed} messages are not as they were")
    return f"{moved} messages back in the inbox, keyword off"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("the inbox before", before),
    ("sorting in shadow", shadow),
    ("sorting in full", full),
    ("the mail put back", put_back_check),
]


async def run(settings: Settings) -> int:
    async with connect_mailbox(settings) as mailbox:
        live = Live(settings, mailbox)
        try:
            failed = await run_checks(live, CHECKS, stop=True)
        finally:
            # A check that failed or a run cut short leaves no mail moved.
            if not live.put_back_done:
                moved = await put_back(live.mailbox, live.before, *live.keywords)
                if moved:
                    print(f"         {moved} messages back in the inbox")
    return 1 if failed else 0


if __name__ == "__main__":
    found = parse_settings("sorting", "The live check of sorting.")
    sys.exit(asyncio.run(run(found)))
