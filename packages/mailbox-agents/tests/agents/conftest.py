"""Fixtures the tests of the agents share."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ..agents_fake import invented, wire_message
from ..agents_helpers import Wired, wired
from .awaiting_reply_helpers import World


@pytest.fixture
async def awaiting_world(tmp_path: Path) -> AsyncIterator[World]:
    async with wired(tmp_path) as found:
        made = World(found)
        await made.start()
        yield made


@pytest.fixture
async def invoices_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        for message in invented():
            found.service.add(message, change=None)
        found.service.add(
            wire_message(
                "filed",
                folder_ids=["inv-hosting"],
                subject="Ihre Rechnung R-77",
                sender="billing@hosting.example",
                text="Ihre Rechnung R-77 liegt bei.",
            ),
            change=None,
        )
        found.service.add(
            wire_message(
                "at-top",
                folder_ids=["inv"],
                subject="Ihre Rechnung R-78",
                text="Ihre Rechnung R-78 liegt bei.",
            ),
            change=None,
        )
        yield found
