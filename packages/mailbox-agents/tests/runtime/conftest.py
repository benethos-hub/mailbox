"""Fixtures the tests of the runtime share."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ..agents_fake import wire_message
from ..agents_helpers import Wired, wired


@pytest.fixture
async def actions_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(wire_message("m1", keywords=["$seen"]))
        yield found
