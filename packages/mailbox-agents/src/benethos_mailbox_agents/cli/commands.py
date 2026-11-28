"""The commands. Each takes the parsed arguments and the settings and
answers the exit code. What they print names ids, counts and paths, never
anything of a mail, except ``report``, which is for the owner."""

from __future__ import annotations

import argparse
import asyncio
import functools
import signal
import tempfile
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from .. import peers
from ..cockpit.app import Cockpit, make_app
from ..cockpit.server import serve
from ..cockpit.sources import Files, Servers, Source
from ..contract import Agent, load_agent
from ..errors import (
    ConfigError,
    StateFileError,
    UnavailableError,
)
from ..evaluation.gold import GoldItem, load_gold
from ..evaluation.report import build, render, write
from ..evaluation.run import evaluate as run_evaluation
from ..logbook import process, record
from ..peers import Card, Server
from ..runtime.classify import PeerClassifier
from ..runtime.health import check
from ..runtime.readiness import MAILBOX_SETTINGS, start
from ..settings import Settings, folders
from ..store import STATES, Store
from .report import report as make_report
from .session import (
    Session,
    mailbox_for,
    now,
    session,
    state_reader,
    upstreams,
)
from .status import _counts, _say

__all__ = [
    "backfill",
    "check_lists",
    "cockpit",
    "evaluate",
    "health",
    "report",
    "run",
    "worker",
]


# -- worker -------------------------------------------------------------------


def worker(args: argparse.Namespace, settings: Settings) -> int:
    if settings.a2a_port:
        # Before anything is opened: the entrance takes no peer unasked.
        settings.secret("a2a_token")
    asyncio.run(_worker(args.agent, settings))
    return 0


def _stop_on_signals(stop: asyncio.Event) -> None:
    """Set ``stop`` on SIGTERM and SIGINT, where the platform lets a loop
    handle them. Elsewhere Ctrl+C ends the process as usual."""
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is not None:
            with suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(number, stop.set)


async def _worker(name: str, settings: Settings) -> None:
    async with session(load_agent(name), settings) as found:
        record(
            process.Started(
                agent=found.agent.label,
                version=found.agent.version,
                stage=settings.stage,
            )
        )
        stop = asyncio.Event()
        _stop_on_signals(stop)
        with ExitStack() as serving:
            if settings.metrics_port:
                serving.enter_context(
                    found.worker.metrics.serving(settings.metrics_port)
                )
                record(
                    process.MetricsServing(
                        agent=found.agent.label, port=settings.metrics_port
                    )
                )
            if settings.a2a_port:
                async with _peers(found, settings):
                    await found.worker.run(stop)
            else:
                await found.worker.run(stop)
        record(process.Stopped(agent=found.agent.label, reason="signal"))


@asynccontextmanager
async def _peers(found: Session, settings: Settings) -> AsyncIterator[None]:
    """The entrance for peers over A2A beside the worker, on its port,
    stopped when the worker stops."""
    token = settings.secret("a2a_token")
    classifier = PeerClassifier(
        found.agent,
        reader=found.mailbox,
        gateway=found.gateway,
        store=found.store,
        now=now,
    )
    url = settings.a2a_url or f"http://{settings.a2a_host}:{settings.a2a_port}/"
    card = Card(name=found.agent.label, version=found.agent.version, url=url)
    server = Server(
        peers.app(classifier.classify, card, token),
        settings.a2a_host,
        settings.a2a_port,
    )
    async with server.serving():
        record(process.A2AServing(agent=found.agent.label, port=settings.a2a_port))
        yield


# -- run and backfill -------------------------------------------------------------


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(_run(args.agent, settings))


async def _run(name: str, settings: Settings) -> int:
    async with session(load_agent(name), settings) as found:
        await found.worker.run_pass()
        print(f"{found.agent.label}: {_counts(found.store)}")
        return 1 if found.worker.away else 0


def backfill(args: argparse.Namespace, settings: Settings) -> int:
    days = args.days if args.days is not None else settings.backfill_days
    if days < 0:
        raise ConfigError("--days must not be negative")
    return asyncio.run(_backfill(args.agent, days, settings))


async def _backfill(name: str, days: int, settings: Settings) -> int:
    async with session(load_agent(name), settings) as found:
        added = await found.worker.backfill(days, again=True)
        await found.worker.drain()
        print(f"{found.agent.label}: {added} taken up, {_counts(found.store)}")
        return 0


# -- report -------------------------------------------------------------------------


def report(args: argparse.Namespace, settings: Settings) -> int:
    agent = load_agent(args.agent)(settings)
    name = agent.label
    if args.state is not None and args.state not in STATES:
        raise ConfigError(f"--state is one of {', '.join(STATES)}")
    if args.limit < 1:
        raise ConfigError("--limit must be at least 1")
    missing = settings.missing(MAILBOX_SETTINGS)
    if missing and not args.offline:
        raise ConfigError(
            f"the report fetches subject and sender and misses {', '.join(missing)}"
            ", or ask for it --offline"
        )
    lines = asyncio.run(
        make_report(
            agent, settings, limit=args.limit, state=args.state, offline=args.offline
        )
    )
    print("\n".join(lines) if lines else f"{name}: nothing recorded yet")
    return 0


# -- check ----------------------------------------------------------------------------


def check_lists(args: argparse.Namespace, settings: Settings) -> int:
    """0 when the configurations of the instances fit together, 1 with a
    line per problem when they do not."""
    agent = load_agent(args.agent)
    configured: dict[str, Path] = {}
    for item in args.instances:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            raise ConfigError(f"{item!r} is not instance=file")
        configured[name] = Path(path)
    problems = agent.check_together(configured)
    for line in problems:
        _say(f"{agent.name}: {line}")
    if not problems:
        _say(f"{agent.name}: {len(configured)} lists, no problem found")
    return 1 if problems else 0


# -- health ---------------------------------------------------------------------------


def health(args: argparse.Namespace, settings: Settings) -> int:
    """0 while the agent's loop makes progress, 1 when it does not, a
    state file not there yet or one that cannot be read included: Docker
    keeps 2 for itself."""
    agent = load_agent(args.agent)
    name = agent.name
    if settings.instance:
        name = f"{name}/{settings.instance}"
    try:
        reader = state_reader(agent.name, settings)
        if reader is None:
            print(f"{name}: unhealthy, no progress yet")
            return 1
        with reader as store:
            found = check(store, settings, now())
    except (StateFileError, ConfigError, UnavailableError) as exc:
        print(f"{name}: unhealthy, {exc.message}")
        return 1
    print(f"{name}: {'healthy' if found.healthy else 'unhealthy'}, {found.reason}")
    return 0 if found.healthy else 1


# -- cockpit --------------------------------------------------------------------------


def cockpit(args: argparse.Namespace, settings: Settings) -> int:
    """Serve the cockpit until stopped. Without its secret it does not
    start, and without the mailbox service it shows the ids alone."""
    given = settings.secret("cockpit_secret")
    mailbox = None
    if not settings.missing(MAILBOX_SETTINGS):
        mailbox = functools.partial(mailbox_for, settings)
    # The servers first: a file left by storage move does not hide
    # the database of its name.
    places: tuple[Source, ...] = (Files(settings.data_dir),)
    if settings.cockpit_database_urls:
        places = (Servers(tuple(settings.cockpit_servers())), *places)
    found = Cockpit(places=places, secret=given, mailbox=mailbox, now=now)
    # Ctrl+C ends it: uvicorn raises the interrupt again once it closed.
    with suppress(KeyboardInterrupt):
        asyncio.run(
            serve(
                make_app(found),
                settings.cockpit_host,
                settings.cockpit_port,
                named=mailbox is not None,
            )
        )
    return 0


# -- eval -----------------------------------------------------------------------------


def evaluate(args: argparse.Namespace, settings: Settings) -> int:
    """Run an agent over a gold set, print the scores, write the report."""
    cls = load_agent(args.agent)
    items = load_gold(args.gold)
    built = asyncio.run(_evaluate(cls, items, settings, args.recognizer))
    for line in render(built):
        print(line)
    print(f"report: {write(built, args.reports or _reports(args, settings))}")
    return 0


def _reports(args: argparse.Namespace, settings: Settings) -> Path:
    """Where a report goes when --reports names no folder: the
    repository's folder for them in its layout, else beside the state
    files."""
    if folders(args.env_file).origin == "working directory":
        return Path("reports") / "mailbox-agents"
    return settings.data_dir / "reports"


async def _evaluate(
    cls: type[Agent], items: list[GoldItem], settings: Settings, part: str | None
) -> dict[str, Any]:
    agent = start(cls, settings)
    if part is not None:
        agent = agent.alone(part)
    async with upstreams(agent, settings) as (mailbox, gateway):
        # It reads mail and writes a report that is kept: only from a
        # service that matches, as a pass.
        await mailbox.ensure_matching()
        with tempfile.TemporaryDirectory() as folder:
            with Store.open(Path(folder) / "evaluation.db") as store:
                outcomes = await run_evaluation(
                    agent, items, reader=mailbox, gateway=gateway, store=store, now=now
                )
    return build(agent, gateway.model, outcomes, now())
