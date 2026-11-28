"""What the tests share: the root of the repository and ``load_script``
for a script outside the package, an agent for the tests, the
pieces wired over the fakes of ``agents_fake.py``, ``configure`` for the
command line, and a look at what became of a message."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from benethos_mailbox_agents.contract import (
    Action,
    ActionRequest,
    Agent,
    Context,
    Route,
    Trigger,
)
from benethos_mailbox_agents.llm.gateway import Gateway
from benethos_mailbox_agents.records import (
    LABEL,
    Decision,
    Event,
    Evidence,
    MailMessage,
    MessageRef,
    OpenItem,
    Profile,
)
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox, connect
from benethos_mailbox_agents.store import Store

from .agents_fake import ACCOUNT, FakeGateway, FakeService
from .clocks import Clock

# The root of the repository, the folder of this package in it, and the
# folder of its documents: what the tests of files beside the code read.
ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "mailbox-agents"


@contextmanager
def load_script(path: Path, name: str) -> Iterator[ModuleType]:
    """The script at ``path`` as the module ``name``, loaded by its path as
    it runs beside what it imports, an ``__init__.py`` as the package
    ``name`` with its modules beside it. Afterwards ``sys.path`` is as it
    was, and the script, its modules and every module it brought from a
    folder it put on the path are gone from ``sys.modules``."""
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    beside = [str(path.parent)] if path.name == "__init__.py" else None
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=beside
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs, as an import does: a dataclass of the
    # script looks its module up there before Python 3.15.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        added = [Path(p) for p in sys.path if p not in path_before]
        sys.path[:] = path_before
        for key in set(sys.modules) - modules_before:
            file = getattr(sys.modules[key], "__file__", None)
            if (
                key == name
                or key.startswith(f"{name}.")
                or (file and any(Path(file).is_relative_to(d) for d in added))
            ):
                del sys.modules[key]


class EchoAnswer(BaseModel):
    label: Literal["match", "other"]
    quote: str


def render(message: MailMessage) -> str:
    return f"Subject: {message.subject or ''}\n\n{message.text}"


class Echo(Agent):
    """Asks the model whether a message in the inbox matches, and sets its
    keyword on one that does."""

    name = "echo"
    version = "1"
    description = "an agent for the runtime tests"
    triggers = Trigger(routes={"message.created": Route.DECIDE})
    actions = frozenset({Action.ADD_KEYWORD, Action.MOVE_TO_FOLDER})
    default_keyword = "echo"
    prompt_version = "p1"
    report_labels = frozenset({"match", "other"})

    def select(self, event: Event) -> Route | None:
        return Route.DECIDE if event.type in self.triggers.events else None

    def admit(self, message: MailMessage) -> bool:
        return message.in_role("inbox")

    def baseline(self, message: MailMessage) -> Decision:
        found = "invoice" in (message.subject or "").lower()
        return Decision(label="match" if found else "other", source="baseline")

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        answer = await context.model.ask(
            system="Say whether it matches.",
            content=render(message),
            evidence=[message.subject or "", message.text],
            schema=EchoAnswer,
        )
        return Decision(
            label=answer.label,
            source="model",
            evidence=(Evidence(field=LABEL, value=answer.label, quote=answer.quote),),
        )

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        if decision.label != "match":
            return []
        return [ActionRequest(Action.ADD_KEYWORD, message.ref, keyword=self.keyword)]


@dataclass
class Collected:
    """The effects a step runner handed on, for a test without an executor."""

    requests: list[ActionRequest] = field(default_factory=list)

    async def __call__(self, requests: list[ActionRequest]) -> None:
        self.requests.extend(requests)


@dataclass
class Wired:
    service: FakeService
    fake_gateway: FakeGateway
    mailbox: Mailbox
    gateway: Gateway
    store: Store
    clock: Clock


@asynccontextmanager
async def wired(tmp_path: Path) -> AsyncIterator[Wired]:
    """The fakes, a mailbox and a gateway over them, a state file, a clock."""
    service, fake_gateway = FakeService(), FakeGateway()
    async with (
        connect(
            "https://mailbox.example.test",
            "service-token",
            transport=service.transport(),
        ) as mailbox,
        Gateway(
            "https://gateway.example.test/v1",
            "gateway-key",
            "alias",
            timeout=120.0,
            transport=fake_gateway.transport(),
        ) as gateway,
    ):
        with Store.open(tmp_path / "echo.db") as store:
            yield Wired(service, fake_gateway, mailbox, gateway, store, Clock())


def profile(started: datetime) -> Profile:
    """The profile of ``counting`` in shadow, as its worker writes it when
    it starts at ``started``."""
    return Profile(
        agent="counting",
        instance=None,
        agent_version="1",
        package_version="0.11.1",
        stage="shadow",
        accounts=(),
        keyword="agent-counted",
        poll_seconds=60.0,
        gateway_timeout_seconds=120.0,
        model_alias="",
        prompt_version="",
        started=started,
    )


def settings(**values: object) -> Settings:
    return Settings(model="alias", **values)


def configure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The settings the command line needs to reach the fake service."""
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_URL", "https://mailbox.example.test")
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_TOKEN", "service-token")


def worker(world: Wired, agent: Agent | None = None, **values: object) -> Worker:
    """A worker over the fakes, for ``agent`` or an Echo in stage full."""
    return Worker(
        agent=agent or Echo(settings(stage="full", **values)),
        store=world.store,
        mailbox=world.mailbox,
        gateway=world.gateway,
        now=world.clock,
    )


async def run(
    world: Wired, message_id: str, agent: Agent, *, again: bool = False
) -> str:
    """Take the message up, anew with ``again`` as ``backfill`` does, run
    its steps with ``agent``, and answer the state it is left in."""
    ref = MessageRef(account_id=ACCOUNT, message_id=message_id)
    world.store.enqueue(ref, world.clock(), again=again)
    await worker(world, agent).process_due()
    row = world.store.message(ref)
    assert row is not None
    return row.state


def mail(world: Wired, message_id: str) -> dict[str, Any]:
    """The message as the fake service holds it."""
    return world.service.messages[(ACCOUNT, message_id)]


def decision(world: Wired, message_id: str) -> dict[str, Any]:
    """The decision stored last for the message."""
    ref = MessageRef(account_id=ACCOUNT, message_id=message_id)
    found = [s for s in world.store.steps(ref) if s.step == "decision"]
    assert found
    return found[-1].result


def actions(world: Wired, message_id: str) -> list[tuple[str, str, bool]]:
    """Each action stored for the message: what, on what, and whether it
    was carried out."""
    ref = MessageRef(account_id=ACCOUNT, message_id=message_id)
    return [(a.action, a.argument, a.executed) for a in world.store.actions(ref)]


def item(world: Wired, message_id: str) -> OpenItem | None:
    """The item of the message, open or closed."""
    return world.store.item(MessageRef(account_id=ACCOUNT, message_id=message_id))
