"""Fixtures the tests of the agents share."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ...agents_helpers import wired
from .awaiting_reply_helpers import World


@pytest.fixture
async def awaiting_world(tmp_path: Path) -> AsyncIterator[World]:
    async with wired(tmp_path) as found:
        made = World(found)
        await made.start()
        yield made
