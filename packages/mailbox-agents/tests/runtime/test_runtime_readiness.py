"""What status says of an agent's folders, and that it says what the
executor does."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from benethos_mailbox_agents.contract import Action, ActionRequest
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.records import FolderRef, MessageRef
from benethos_mailbox_agents.runtime.actions import Executor, Outcome
from benethos_mailbox_agents.runtime.readiness import (
    accounts_of,
    folder_lines,
    readiness,
    start,
)

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Echo, Wired, settings, wired

REF = MessageRef(account_id=ACCOUNT, message_id="m1")


@pytest.fixture
async def readiness_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(wire_message("m1"), change=None)
        yield found


async def test_the_accounts_are_those_named_or_else_those_granted(
    readiness_world: Wired,
) -> None:
    assert await accounts_of(settings(accounts=["named"]), readiness_world.mailbox) == [
        "named"
    ]
    assert await accounts_of(settings(), readiness_world.mailbox) == [ACCOUNT]


class Described(Echo):
    """Names three folders it expects and describes those that are there."""

    def folders_needed(self) -> tuple[str, ...]:
        return ("Invoices/Hosting", "invoices/hosting", "Missing")

    def describe_folders(self, folders: Mapping[str, FolderRef]) -> list[str]:
        return [
            f"{path}: looked in" for path in self.folders_needed() if path in folders
        ]


async def test_the_lines_of_the_folders_of_an_agent(readiness_world: Wired) -> None:
    lines = await folder_lines(Described(settings()), readiness_world.mailbox)

    assert lines[0] == f"folders in {ACCOUNT}:"
    assert "  Invoices/Hosting: looked in" in lines
    assert lines[-2:] == [
        f"folder in another case in {ACCOUNT}: invoices/hosting",
        f"folder missing in {ACCOUNT}: Missing",
    ]


class Expecting(Echo):
    """Expects one folder and may make it."""

    actions = frozenset({Action.CREATE_FOLDER})
    expected = ""

    def folders_needed(self) -> tuple[str, ...]:
        return (self.expected,)

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        return True


@pytest.mark.parametrize(
    ("path", "another_case"),
    [("invoices", True), ("INVOICES", True), ("Invoices", False), ("Elsewhere", False)],
)
async def test_status_says_another_case_where_the_executor_refuses_it(
    readiness_world: Wired, path: str, another_case: bool
) -> None:
    agent = Expecting(settings(stage="full"))
    agent.expected = path
    executor = Executor(
        agent=agent,
        store=readiness_world.store,
        mailbox=readiness_world.mailbox,
        now=readiness_world.clock,
    )

    said = await folder_lines(agent, readiness_world.mailbox)
    done = await executor([ActionRequest(Action.CREATE_FOLDER, REF, folder=path)])

    assert (f"folder in another case in {ACCOUNT}: {path}" in said) is another_case
    assert (done == [Outcome.REFUSED]) is another_case


class Configured(Echo):
    """Asks a model or not, as its configuration says once prepared."""

    asks = False
    prepared = False

    def prepare(self) -> None:
        self.prepared = True

    def asks_model(self) -> bool:
        assert self.prepared, "asked before it was prepared"
        return self.asks


MAILBOX = {"service_url": "https://mailbox.example.test", "service_token": "t"}
# The model alias the helper sets: the gateway's URL and key are missing.
GATEWAY = ("MAILBOX_AGENTS_GATEWAY_URL", "MAILBOX_AGENTS_GATEWAY_KEY")


def test_an_agent_that_asks_no_model_starts_without_the_gateway() -> None:
    Configured.asks = False

    found = readiness(Configured, settings(**MAILBOX))

    assert found.ready and found.agent is not None
    assert not start(Configured, settings(**MAILBOX)).asks_model()


def test_an_agent_that_asks_a_model_misses_the_gateway() -> None:
    Configured.asks = True

    found = readiness(Configured, settings(**MAILBOX))

    assert found.missing == GATEWAY
    with pytest.raises(
        ConfigError, match="echo misses settings: MAILBOX_AGENTS_GATEWAY"
    ):
        start(Configured, settings(**MAILBOX))


def test_the_gateway_is_named_with_the_mailbox_service() -> None:
    Configured.asks = True

    found = readiness(Configured, settings())

    assert found.missing == (
        "MAILBOX_AGENTS_SERVICE_URL",
        "MAILBOX_AGENTS_SERVICE_TOKEN",
        *GATEWAY,
    )
