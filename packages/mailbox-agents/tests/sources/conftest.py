"""Fixtures the tests of the sources share: the fake mailbox service and
a mailbox over it."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from benethos_mailbox_agents.sources.mailbox import Mailbox, connect

from ..agents_fake import FakeService


@pytest.fixture
def fake_service() -> FakeService:
    return FakeService()


@pytest.fixture
async def mailbox(fake_service: FakeService) -> AsyncIterator[Mailbox]:
    async with connect(
        "https://mailbox.example.test",
        "token-value",
        transport=fake_service.transport(),
    ) as opened:
        yield opened
