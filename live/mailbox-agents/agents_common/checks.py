"""The run of the checks and what they share: a check skipped, the agent
``sorting`` over the test account, and the labels a state file holds."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TypeVar

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import ActionRow, Store

from .settings import DAYS, LIST
from .upstreams import worker

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
    """The agent ``sorting`` with the list containers/live/mailbox-agents/sorting.json,
    in ``stage``, over the mail of the last :data:`DAYS` days, with its state
    file in ``folder``. Answers its actions and how many messages it
    decided for each label."""
    found = settings.model_copy(
        update={"stage": stage, "sorting_file": LIST, "data_dir": folder}
    )
    agent = Sorting(found)
    agent.prepare()
    with Store.open(folder / "sorting.db") as store:
        sorting = worker(agent, store, mailbox)
        await sorting.backfill(DAYS)
        await sorting.drain()
        return store.actions(), labels(store)


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
