"""Fixtures the test modules share."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from benethos_mailbox_agents.cli import session
from benethos_mailbox_agents.settings import DEFAULT_ENV_FILE, PREFIX
from benethos_mailbox_common.log import redact
from benethos_mailbox_common.paths import folders as system

from .agents_fake import FakeGateway, FakeService
from .agents_helpers import Wired, wired


@pytest.fixture(autouse=True)
def no_configuration_from_this_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """No setting of this machine's environment reaches a test, no secret
    noted by one is masked in the next, and the folders of the operating
    system are folders of the test: no test reads or writes the real
    ones."""
    for name in list(os.environ):
        if name.startswith(PREFIX):
            monkeypatch.delenv(name)
    folders = tmp_path_factory.mktemp("system")
    monkeypatch.setattr(
        system,
        "system_folders",
        lambda app: system.SystemFolders(
            config=folders / "config", data=folders / "data"
        ),
    )
    redact.forget()
    yield
    redact.forget()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeService:
    """A working directory of its own in the layout of the repository,
    settings for the fakes, the fakes as the transports of the command
    line."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_ENV_FILE.parent).mkdir(parents=True)
    found = FakeService()
    monkeypatch.setitem(session.TRANSPORTS, "service", found.transport())
    monkeypatch.setitem(session.TRANSPORTS, "gateway", FakeGateway().transport())
    return found


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[Wired]:
    """The fakes over an empty mailbox. A module that needs mail in it
    defines a world of its own."""
    async with wired(tmp_path) as found:
        yield found
