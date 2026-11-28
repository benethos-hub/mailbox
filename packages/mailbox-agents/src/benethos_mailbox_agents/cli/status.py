"""The commands status and paths: whether each agent is ready, its
folders and its state, the mailbox service and its version, and where
the settings and the states lie. What they print names ids, counts and
paths, never anything of a mail."""

from __future__ import annotations

import argparse
import asyncio

from benethos_mailbox_common.values import text as text_values

from ..contract import Agent, discover, label_of, state_name
from ..errors import (
    ConfigError,
    MailboxAgentError,
    ServiceVersionError,
    StateFileError,
    UnavailableError,
)
from ..runtime.readiness import MAILBOX_SETTINGS, folder_lines, readiness
from ..settings import PREFIX, Settings, folders
from ..sources.versions import matches, shown, taken
from ..store import Store, earlier_file
from .session import (
    former_file,
    mailbox_for,
    server_place_shown,
    server_reader,
    state_file,
)

__all__ = ["paths", "status"]


def _counts(store: Store) -> str:
    return " ".join(f"{state}={count}" for state, count in store.counts().items())


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
    on_server = settings.storage == "postgres"
    shown = _server_state(settings) if on_server else {}
    for cls in discover().values():
        found = readiness(cls, settings)
        if found.ready:
            state = "ready"
        elif found.missing:
            state = "misses " + ", ".join(found.missing)
        else:
            state = f"not ready: {found.problem}"
        _say(f"{label_of(found.name, settings.instance)} {found.version}: {state}")
        if found.agent is not None:
            for line in _folders(found.agent, settings):
                _say(f"  {line}")
        for line in (
            shown.get(cls.name, []) if on_server else _state(cls.name, settings)
        ):
            _say(f"  {line}")
        former = former_file(settings.data_dir, cls, settings.instance)
        if former is not None:
            _say(
                f"  a state file lies at {former.resolve()} under a former name: "
                "rename it to the agent's name"
            )
    return 0


def _state(name: str, settings: Settings) -> list[str]:
    """What the state file of agent ``name`` says, and where one lies at
    the place before."""
    path = state_file(name, settings)
    earlier = earlier_file(settings.data_dir, state_name(name, settings.instance))
    if earlier is not None:
        where = path.resolve()
        return [f"a state file lies at {earlier.resolve()}: move it to {where}"]
    if not path.is_file():
        return []
    try:
        with Store.open(path, read_only=True) as store:
            lines = _lines(store)
    except (StateFileError, ConfigError) as exc:
        return [f"state file unreadable: {exc.message}"]
    return [f"state: {path.resolve()}", *lines]


def _lines(store: Store) -> list[str]:
    last = store.progress()
    return [_counts(store), f"last progress: {last.isoformat() if last else 'none'}"]


def _server_state(settings: Settings) -> dict[str, list[str]]:
    """The state on the server the settings name, read once: where it
    lies, said at once, and its lines under the agent whose profile it
    holds."""
    _say(f"state: {server_place_shown(settings)}")
    try:
        reader = server_reader(settings)
        if reader is None:
            _say("  nothing yet: no agent has started on it")
            return {}
        with reader as store:
            profile = store.profile()
            lines = _lines(store)
    except (StateFileError, ConfigError, UnavailableError) as exc:
        _say(f"  unreadable: {exc.message}")
        return {}
    if profile is None:
        return {}
    return {profile.agent: lines}


def paths(args: argparse.Namespace, settings: Settings) -> int:
    env = folders(args.env_file).env_file
    print(f"settings: {env.resolve()} ({'found' if env.is_file() else 'missing'})")
    print(f"data: {settings.data_dir.resolve()}")
    if settings.storage == "postgres":
        print(f"state: {server_place_shown(settings)}")
        return 0
    for name in discover():
        path = state_file(name, settings)
        print(
            f"  {name}: {path.resolve()} ({'found' if path.is_file() else 'none yet'})"
        )
        earlier = earlier_file(settings.data_dir, state_name(name, settings.instance))
        if earlier is not None:
            print(f"    a state file lies at {earlier.resolve()}: move it here")
    return 0
