"""The commands. Each takes the parsed arguments and the settings and
answers the exit code. What they print names ids, counts and paths, never
anything of a mail, except ``report``, which is for the owner."""

from __future__ import annotations

import argparse
import asyncio
import signal
import tempfile
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import Any

from benethos_mailbox_common.values import text as text_values

from ..contract import Agent, discover, load_agent, state_name
from ..errors import (
    ConfigError,
    MailboxAgentError,
    ServiceVersionError,
    StateFileError,
)
from ..evaluation.gold import GoldItem, load_gold
from ..evaluation.report import build, render, write
from ..evaluation.run import evaluate as run_evaluation
from ..logbook import process, record
from ..runtime.health import check
from ..runtime.readiness import MAILBOX_SETTINGS, folder_lines, readiness, start
from ..settings import PREFIX, Settings, folders
from ..sources.versions import matches, shown, taken
from ..store import STATES, Store, earlier_file, path_for
from .report import report as make_report
from .session import mailbox_for, now, session, upstreams

__all__ = [
    "backfill",
    "evaluate",
    "health",
    "paths",
    "report",
    "run",
    "status",
    "worker",
]


def _counts(store: Store) -> str:
    return " ".join(f"{state}={count}" for state, count in store.counts().items())


# -- worker -------------------------------------------------------------------


def worker(args: argparse.Namespace, settings: Settings) -> int:
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
            await found.worker.run(stop)
        record(process.Stopped(agent=found.agent.label, reason="signal"))


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


# -- status and paths -------------------------------------------------------------


def _folders(agent: Agent, settings: Settings) -> list[str]:
    """What ``status`` says of the folders of a prepared agent that expects
    some: the folders that matter in each account it works on, each one
    it expects that is missing or there in another case only, or why they
    were not looked up."""
    if not agent.folders_needed():
        return []
    try:
        return asyncio.run(_folder_lines(agent, settings))
    except MailboxAgentError as exc:
        return [f"folders not checked: {exc.message}"]


async def _folder_lines(agent: Agent, settings: Settings) -> list[str]:
    async with mailbox_for(settings) as mailbox:
        return await folder_lines(agent, mailbox)


def _service(settings: Settings) -> str | None:
    """What ``status`` says of the mailbox service: its version and whether
    it matches the agents', or why it was not asked. None while the
    settings name no service, which each agent's line says already."""
    if settings.missing(MAILBOX_SETTINGS):
        return None
    try:
        found = asyncio.run(_version(settings))
    except ServiceVersionError:
        return (
            "mailbox service names no version: no match, no agent starts "
            f"(the agents take {taken()})"
        )
    except MailboxAgentError as exc:
        return f"mailbox service not asked: {exc.message}"
    if matches(found):
        return f"mailbox service {found}: matches (the agents take {taken()})"
    return (
        f"mailbox service {shown(found)}: no match, no agent starts "
        f"(the agents take {taken()})"
    )


async def _version(settings: Settings) -> str:
    async with mailbox_for(settings) as mailbox:
        return await mailbox.version()


def _say(line: str) -> None:
    """Print one line of ``status``. A folder's name is the owner's or the
    server's: a control or direction character in it is written escaped,
    as in ``report``."""
    print(text_values.escaped(line))


def status(args: argparse.Namespace, settings: Settings) -> int:
    if settings.keyword is not None:
        _say(
            f"{PREFIX}KEYWORD is set for every agent of these settings: "
            "give each agent its own env file"
        )
    service = _service(settings)
    if service is not None:
        _say(service)
    for cls in discover().values():
        found = readiness(cls, settings)
        if found.ready:
            state = "ready"
        elif found.missing:
            state = "misses " + ", ".join(found.missing)
        else:
            state = f"not ready: {found.problem}"
        name = f"{found.name}/{settings.instance}" if settings.instance else found.name
        _say(f"{name} {found.version}: {state}")
        if found.agent is not None:
            for line in _folders(found.agent, settings):
                _say(f"  {line}")
        for line in _state(cls.name, settings):
            _say(f"  {line}")
    return 0


def _state(name: str, settings: Settings) -> list[str]:
    """What the state file of agent ``name`` says, and where one lies at
    the place before."""
    path = path_for(settings.data_dir, state_name(name, settings.instance))
    earlier = earlier_file(settings.data_dir, state_name(name, settings.instance))
    if earlier is not None:
        where = path.resolve()
        return [f"a state file lies at {earlier.resolve()}: move it to {where}"]
    if not path.is_file():
        return []
    try:
        with Store.open(path, read_only=True) as store:
            last = store.progress()
            counts = _counts(store)
    except (StateFileError, ConfigError) as exc:
        return [f"state file unreadable: {exc.message}"]
    return [counts, f"last progress: {last.isoformat() if last else 'none'}"]


def paths(args: argparse.Namespace, settings: Settings) -> int:
    env = folders(args.env_file).env_file
    print(f"settings: {env.resolve()} ({'found' if env.is_file() else 'missing'})")
    print(f"data: {settings.data_dir.resolve()}")
    for name in discover():
        path = path_for(settings.data_dir, state_name(name, settings.instance))
        print(
            f"  {name}: {path.resolve()} ({'found' if path.is_file() else 'none yet'})"
        )
        earlier = earlier_file(settings.data_dir, state_name(name, settings.instance))
        if earlier is not None:
            print(f"    a state file lies at {earlier.resolve()}: move it here")
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
    path = path_for(settings.data_dir, state_name(agent.name, settings.instance))
    if not path.is_file():
        print(f"{name}: unhealthy, no progress yet")
        return 1
    try:
        with Store.open(path, read_only=True) as store:
            found = check(store, settings, now())
    except (StateFileError, ConfigError) as exc:
        print(f"{name}: unhealthy, {exc.message}")
        return 1
    print(f"{name}: {'healthy' if found.healthy else 'unhealthy'}, {found.reason}")
    return 0 if found.healthy else 1


# -- eval -----------------------------------------------------------------------------


def evaluate(args: argparse.Namespace, settings: Settings) -> int:
    """Run an agent over a gold set, print the scores, write the report."""
    cls = load_agent(args.agent)
    items = load_gold(args.gold)
    built = asyncio.run(_evaluate(cls, items, settings))
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
    cls: type[Agent], items: list[GoldItem], settings: Settings
) -> dict[str, Any]:
    agent = start(cls, settings)
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
