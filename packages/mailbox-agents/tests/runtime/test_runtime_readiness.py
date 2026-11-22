"""What status says of an agent's folders, and that it says what the
executor does."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from benethos_mailbox_agents.agents.invoices.agent import Invoices
from benethos_mailbox_agents.contract import Action, ActionRequest
from benethos_mailbox_agents.records import FolderRef, MessageRef
from benethos_mailbox_agents.runtime.actions import Executor, Outcome
from benethos_mailbox_agents.runtime.readiness import accounts_of, folder_lines

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


async def test_the_lines_of_the_folders_of_an_agent(readiness_world: Wired) -> None:
    agent = Invoices(
        settings(invoices_folders=["Invoices/*", "invoices/hosting", "Missing/*"])
    )

    lines = await folder_lines(agent, readiness_world.mailbox)

    assert lines[0] == f"folders in {ACCOUNT}:"
    assert "  Invoices/Hosting: looked in, an invoice is marked and stays" in lines
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
