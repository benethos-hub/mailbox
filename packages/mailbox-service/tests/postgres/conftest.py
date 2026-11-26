"""What the tests against the server share."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_service.data.storage import Database

from ..schema_helpers import at_schema

SEED = Path(__file__).parent.parent / "data" / "storage" / "seeds" / "schema_25.sql"


@pytest.fixture
def source(tmp_path: Path) -> Iterator[Database]:
    """A database in SQLite with every table filled: the seed of schema
    25, migrated, without the two values an older version wrote that do
    not fit their columns (a text for a number, a text for bytes)."""
    raw = at_schema(tmp_path / "source.db", 25)
    raw.executescript(SEED.read_text(encoding="utf-8"))
    raw.execute(
        "UPDATE webhook_attempts SET events = CAST(substr(events, 2, 1) AS INTEGER)"
    )
    raw.execute(
        "UPDATE passkeys SET credential_id = CAST(credential_id AS BLOB),"
        " credential = CAST(credential AS BLOB)"
    )
    raw.close()
    opened = Database(tmp_path / "source.db")
    yield opened
    opened.close()
