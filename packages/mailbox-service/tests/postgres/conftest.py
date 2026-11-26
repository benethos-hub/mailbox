"""What the tests against the server share."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_service.data.storage import Database

from ..schema_helpers import seed_25


@pytest.fixture
def source(tmp_path: Path) -> Iterator[Database]:
    """A database in SQLite with every table filled: the seed of schema
    25, migrated, without the two values an older version wrote that do
    not fit their columns (a text for a number, a text for bytes)."""
    opened = seed_25(tmp_path / "source.db", fitting=True)
    yield opened
    opened.close()
