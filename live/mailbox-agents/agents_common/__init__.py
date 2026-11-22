"""What the live checks share: their settings, from their file alone, the
mailbox and the gateway of the settings, a worker, the agent ``sorting``
over the test account and its mail put back, and the run of the checks.

A live check runs against the test account of containers/live/mailbox-agents/ and no
other. So its settings come from its file and from nothing else: a
setting exported in the shell, of a real deployment say, is not read, and
cannot point a check at a real account. A mailbox service that is not on
this machine stops the check with exit code 2 (decided 2026-11-18). The
account and the service are printed before the check reads or writes.

The live scripts import this module beside them, as ``common``, and the
invented mail of containers/live/mailbox-agents/mail.py through it, as ``mail``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlsplit

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.contract import Agent
from benethos_mailbox_agents.errors import MessageGoneError
from benethos_mailbox_agents.llm.gateway import Gateway
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.model import Asker, NoModel
from benethos_mailbox_agents.settings import PREFIX, Settings, load_settings
from benethos_mailbox_agents.sources.mailbox import Mailbox, connect
from benethos_mailbox_agents.store import ActionRow, Store

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "containers" / "live" / "mailbox-agents"
ENV = LIVE / "secrets" / "agent.env"
LIST = LIVE / "sorting.json"
sys.path.insert(0, str(LIVE))

import mail  # noqa: E402 - beside the setup, not a package

__all__ = [
    "DAYS",
    "ENV",
    "LIST",
    "LIVE",
    "LOOPBACK",
    "ROOT",
    "Skip",
    "Snapshot",
    "connect_mailbox",
    "inbox_snapshot",
    "labels",
    "live_settings",
    "mail",
    "open_gateway",
    "parse_settings",
    "put_back",
    "run_checks",
    "snapshot",
    "sort_test_account",
    "worker",
]

# The hosts of a mailbox service on this machine, as containers/live has it.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
# The port containers/live/mailbox-agents/compose.yaml publishes its mailbox service on.
# A service on this machine at another port, such as the default 8080, may be
# a real one: the check refuses it.
LIVE_PORT = 38081

# The days of mail a check reads, as the invented mail of mail.py spans.
DAYS = 30

# Each message of the inbox: its folder ids and its keywords, each sorted.
Snapshot = dict[MessageRef, tuple[tuple[str, ...], tuple[str, ...]]]

Live = TypeVar("Live")


class Skip(Exception):  # noqa: N818 - a reason to skip, not an error
    """Raised by a check that has nothing to check."""


def live_settings(path: Path, script: str) -> Settings:
    """The settings in the file at ``path``, every ``MAILBOX_AGENTS_``
    variable of the environment aside. Exits when the file is missing or
    names no account, and with code 2 when the mailbox service is not the
    one of containers/live, on this machine at :data:`LIVE_PORT`.
    ``script`` names the check in what it says."""
    if not path.is_file():
        sys.exit(
            f"{script}: no settings at {path},"
            " run containers/live/mailbox-agents/setup.sh"
        )
    aside = {
        name: os.environ.pop(name)
        for name in list(os.environ)
        if name.upper().startswith(PREFIX)  # read without regard to case
    }
    try:
        found = load_settings(path)
    finally:
        os.environ.update(aside)
    url = urlsplit(found.service_url or "")
    try:
        port = url.port
    except ValueError:
        port = None
    if url.hostname not in LOOPBACK or port != LIVE_PORT:
        print(
            f"{script}: the mailbox service is not the one of containers/live, "
            f"on this machine at port {LIVE_PORT}: a live check runs against "
            "the test account of containers/live only",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not found.accounts:
        sys.exit(
            f"{script}: the settings name no account, the check needs the test one"
        )
    for account in found.accounts:
        print(f"live: account {account} at {found.service_url}")
    return found


def parse_settings(script: str, description: str) -> Settings:
    """The settings of the file the command line names with ``--env-file``,
    containers/live/mailbox-agents/secrets/agent.env when it names none."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--env-file", type=Path, default=ENV)
    args = parser.parse_args()
    return live_settings(args.env_file, script)


def connect_mailbox(settings: Settings) -> AbstractAsyncContextManager[Mailbox]:
    """The mailbox service of the settings, as the command line connects it."""
    return connect(
        settings.service_url or "",
        settings.secret("service_token"),
        allow_http=settings.service_allow_http,
        verify=settings.ssl_context(),
    )


def open_gateway(settings: Settings) -> Gateway:
    """The model gateway of the settings, as the command line opens it."""
    return Gateway(
        settings.gateway_url or "",
        settings.secret("gateway_key"),
        settings.model or "",
        timeout=settings.gateway_timeout_seconds,
        allow_http=settings.gateway_allow_http,
        verify=settings.ssl_context(),
    )


def worker(
    agent: Agent, store: Store, mailbox: Mailbox, gateway: Asker | None = None
) -> Worker:
    """A worker of ``agent`` over the mailbox, on the clock of this machine,
    with no model unless ``gateway`` is given."""
    return Worker(
        agent=agent,
        store=store,
        mailbox=mailbox,
        gateway=gateway or NoModel(),
        now=lambda: datetime.now(UTC),
    )


def labels(store: Store) -> Counter[str]:
    """How many messages the agent of ``store`` decided for each label, by
    the decision it stored last for each."""
    found: Counter[str] = Counter()
    for row in store.messages(None, 1000):
        steps = [s for s in store.steps(row.ref) if s.step == "decision"]
        if steps:
            found[str(steps[-1].result["label"])] += 1
    return found


async def inbox_snapshot(mailbox: Mailbox, settings: Settings) -> Snapshot:
    """Each message of the inbox of the last :data:`DAYS` days: its folders
    and keywords."""
    since = date.today() - timedelta(days=DAYS)
    refs = await mailbox.recent(since, settings.accounts, roles=("inbox",))
    return await snapshot(mailbox, refs)


async def snapshot(mailbox: Mailbox, refs: Iterable[MessageRef]) -> Snapshot:
    """The folders and keywords of each message of ``refs`` as it lies now,
    fetched one by one. A message gone is left out."""
    found: Snapshot = {}
    for ref in refs:
        try:
            message = await mailbox.message(ref)
        except MessageGoneError:
            continue
        found[ref] = (
            tuple(sorted(f.id for f in message.folders)),
            tuple(sorted(message.keywords)),
        )
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


async def put_back(mailbox: Mailbox, before: Snapshot, *keywords: str) -> int:
    """Put each message of ``before`` back as it lay: into its folder when
    it lies elsewhere now, then with each of ``keywords`` taken off that
    was not on it. Taken from the snapshot, not from the actions of a state
    file, so a run cut short in the middle is put back too. Each message is
    read once: a second look right after a move may still see the folder
    before it. Answers how many messages were moved back."""
    moved = 0
    for ref, (folders, found) in (await snapshot(mailbox, before)).items():
        was_folders, was_keywords = before[ref]
        if folders != was_folders and was_folders:
            await mailbox.move(ref, was_folders[0])
            moved += 1
        on = {k.casefold() for k in found}
        was = {k.casefold() for k in was_keywords}
        for keyword in keywords:
            if keyword.casefold() in on and keyword.casefold() not in was:
                await mailbox.remove_keyword(ref, keyword)
    return moved


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
