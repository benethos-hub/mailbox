"""Whether an agent can start: its settings, and what it reads besides.

``status`` asks this of every agent without starting one, and the lines
of :func:`folder_lines` for the folders that matter to it, in the accounts
:func:`accounts_of` names. :func:`start` builds the agent a command runs,
once. See docs/mailbox-agents/concept/agent-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..contract import Agent, discover
from ..errors import ConfigError, ContractError, MailboxAgentError
from ..records import FolderRef
from ..settings import PREFIX, Settings
from .actions import in_another_case

__all__ = [
    "MAILBOX_SETTINGS",
    "MODEL_SETTINGS",
    "Folders",
    "Readiness",
    "accounts_of",
    "folder_lines",
    "readiness",
    "required",
    "start",
]

# What every agent needs, and what an agent that asks the model needs too.
MAILBOX_SETTINGS = ("service_url", "service_token")
MODEL_SETTINGS = ("gateway_url", "gateway_key", "model")


def required(agent: type[Agent], asks_model: bool) -> tuple[str, ...]:
    """The settings ``agent`` needs before it starts, those of the gateway
    when it asks a model."""
    found = MAILBOX_SETTINGS + (MODEL_SETTINGS if asks_model else ())
    return found + tuple(n for n in agent.requires.settings if n not in found)


def _prepared(cls: type[Agent], settings: Settings) -> Agent | ConfigError | None:
    """The agent built and prepared, or what its preparation found wrong.
    None while a setting it requires of its own is missing, as it cannot be
    prepared then. Whether it asks a model is known only once it is."""
    if settings.missing(cls.requires.settings):
        return None
    try:
        _own_keyword(cls, settings)
        agent = cls(settings)
        agent.prepare()
        if agent.waits_for(agent.keyword):
            raise ConfigError(
                f"the list of {agent.label} waits for the agent's own keyword"
            )
    except (ConfigError, ContractError) as exc:
        return ConfigError(exc.message)
    return agent


def _missing(
    cls: type[Agent], settings: Settings, prepared: Agent | ConfigError | None
) -> list[str]:
    asks = isinstance(prepared, Agent) and prepared.asks_model()
    return settings.missing(required(cls, asks))


@dataclass(frozen=True)
class Readiness:
    """Whether an agent could start. ``agent`` is the agent built and
    prepared, when it is ready, so a caller asks it without preparing a
    second one."""

    name: str
    version: str
    missing: tuple[str, ...]
    problem: str | None
    agent: Agent | None = None

    @property
    def ready(self) -> bool:
        return not self.missing and self.problem is None


def _own_keyword(agent: type[Agent], settings: Settings) -> None:
    """A :class:`ConfigError` when ``MAILBOX_AGENTS_KEYWORD`` is the
    keyword of another agent. Set in env settings that several agents
    share, it gives them one keyword, and an agent that skips its marked
    mail would skip what the other one marked."""
    if settings.keyword is None:
        return
    for other in discover().values():
        if other.name != agent.name and other.default_keyword == settings.keyword:
            raise ConfigError(
                f"{PREFIX}KEYWORD is the keyword of {other.name}: "
                "give each agent its own env file"
            )


def readiness(agent: type[Agent], settings: Settings) -> Readiness:
    """Whether ``agent`` could start with ``settings``: the settings it
    misses, or what its preparation found wrong, or else the agent
    prepared. The settings of the gateway are missing only for an agent
    that, prepared, asks a model."""
    prepared = _prepared(agent, settings)
    missing = tuple(_missing(agent, settings, prepared))
    if missing:
        return Readiness(agent.name, agent.version, missing, None)
    if isinstance(prepared, ConfigError):
        return Readiness(agent.name, agent.version, missing, prepared.message)
    return Readiness(agent.name, agent.version, missing, None, prepared)


def start(cls: type[Agent], settings: Settings) -> Agent:
    """The agent, once its settings and its preparation are found ready.
    It is built and prepared once, what it reads besides read once."""
    prepared = _prepared(cls, settings)
    missing = _missing(cls, settings, prepared)
    if missing:
        raise ConfigError(f"{cls.name} misses settings: {', '.join(missing)}")
    if isinstance(prepared, Agent):
        return prepared
    # Not None: a setting of its own missing is among those missing.
    problem = prepared.message if prepared is not None else "not prepared"
    raise ConfigError(f"{cls.name} is not ready: {problem}")


class Folders(Protocol):
    """What :func:`folder_lines` reads of the mailbox service."""

    async def accounts(self) -> tuple[str, ...]:
        """The ids of the accounts the user is granted."""

    async def folders(self, account_id: str) -> dict[str, FolderRef]:
        """The folders of an account, by id."""


async def accounts_of(settings: Settings, mailbox: Folders) -> list[str]:
    """The accounts an agent works on: those the settings name, or else
    every account the user is granted."""
    return settings.accounts or list(await mailbox.accounts())


async def folder_lines(agent: Agent, mailbox: Folders) -> list[str]:
    """What ``status`` says of the folders of ``agent``, for each account
    it works on: the folders it says matter, and a line for each folder
    it expects that is not there. One whose name is there in another case
    is said so, as the executor neither moves into it nor makes it. An
    account whose folders are refused gets a line of its own, and the
    others are still listed."""
    accounts = await accounts_of(agent.settings, mailbox)
    if not accounts:
        return ["folders not checked: no account is granted"]
    lines = []
    for account in accounts:
        try:
            found = await mailbox.folders(account)
        except MailboxAgentError as exc:
            lines.append(f"folders not checked in {account}: {exc.message}")
            continue
        there = {f.path: f for f in found.values()}
        described = agent.describe_folders(there)
        if described:
            lines.append(f"folders in {account}:")
            lines.extend(f"  {line}" for line in described)
        for path in agent.folders_needed():
            if path in there:
                continue
            if in_another_case(path, there):
                lines.append(f"folder in another case in {account}: {path}")
            else:
                lines.append(f"folder missing in {account}: {path}")
    return lines
