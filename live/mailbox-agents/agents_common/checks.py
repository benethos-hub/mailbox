"""The run of the checks and what they share: a check skipped, the agent
``categorization`` over the test account and the keywords it sets, and the
labels a state file holds."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TypeVar

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import ActionRow, Store

from .settings import DAYS, LIST
from .upstreams import open_gateway, worker

Live = TypeVar("Live")


class Skip(Exception):  # noqa: N818 - a reason to skip, not an error
    """Raised by a check that has nothing to check."""


def labels(store: Store) -> Counter[str]:
    """How many messages the agent of ``store`` decided for each label, by
    the decision it stored last for each."""
    found: Counter[str] = Counter()
    for row in store.messages(None, 1000):
        steps = [s for s in store.steps(row.ref) if s.step == "decision"]
        if steps:
            found[str(steps[-1].result["label"])] += 1
    return found


async def sort_test_account(
    settings: Settings, mailbox: Mailbox, stage: str, folder: Path
) -> tuple[list[ActionRow], Counter[str]]:
    """The agent ``categorization`` with the list
    containers/live/mailbox-agents/categorization.json, in ``stage``,
    over the mail of the last :data:`DAYS` days, with its state file in
    ``folder``, through the gateway of the settings when a group of the
    list has a topic. Answers its actions and how many messages it
    decided for each label."""
    found = settings.model_copy(
        update={"stage": stage, "categorization_file": LIST, "data_dir": folder}
    )
    agent = Categorization(found)
    agent.prepare()
    async with AsyncExitStack() as stack:
        gateway = (
            await stack.enter_async_context(open_gateway(found))
            if agent.asks_model()
            else None
        )
        with Store.open(folder / "categorization.db") as store:
            categorization = worker(agent, store, mailbox, gateway)
            await categorization.backfill(DAYS)
            await categorization.drain()
            return store.actions(), labels(store)


def categorization_keywords(settings: Settings) -> tuple[str, ...]:
    """Every keyword ``categorization`` sets with the list of the live setup: its
    own and those of the list, each to be taken off when the mail is put
    back."""
    agent = Categorization(settings.model_copy(update={"categorization_file": LIST}))
    agent.prepare()
    return tuple(sorted(agent.keywords()))


async def run_checks(
    live: Live,
    checks: Sequence[tuple[str, Callable[[Live], Awaitable[str]]]],
    *,
    stop: bool = False,
) -> int:
    """Each check in turn, each saying ok, skipped or FAILED with what it
    found. With ``stop`` the first that fails ends the run. Answers how
    many failed."""
    failed = 0
    for name, check in checks:
        try:
            said = await check(live)
        except Skip as skip:
            print(f"skipped  {name}: {skip}")
            continue
        except Exception as exc:
            failed += 1
            print(f"FAILED   {name}: {type(exc).__name__}: {exc}")
            if stop:
                break
            continue
        print(f"ok       {name}: {said}")
    return failed
