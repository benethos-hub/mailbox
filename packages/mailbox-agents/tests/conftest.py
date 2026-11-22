"""Fixtures the test modules share."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from benethos_mailbox_agents import errors
from benethos_mailbox_agents.cli import session
from benethos_mailbox_agents.settings import PREFIX

from .agents_fake import FakeGateway, FakeService
from .agents_helpers import Wired, wired


@pytest.fixture(autouse=True)
def no_configuration_from_this_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """No setting of this machine's environment reaches a test, and no
    secret noted by one is masked in the next."""
    for name in list(os.environ):
        if name.startswith(PREFIX):
            monkeypatch.delenv(name)
    errors.forget_secrets()
    yield
    errors.forget_secrets()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeService:
    """A working directory of its own, settings for the fakes, the fakes
    as the transports of the command line."""
    monkeypatch.chdir(tmp_path)
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
