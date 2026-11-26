"""The move of the records: the check before anything is written names
every column whose values do not fit its kind, with how many, and never
a value."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_service.data.move import Misfit, misfits, refused
from benethos_mailbox_service.data.storage import Database

from ..schema_helpers import at_schema

SEED = Path(__file__).parent / "storage" / "seeds" / "schema_25.sql"


@pytest.fixture
def seeded(tmp_path: Path) -> Database:
    """The seed of schema 25, migrated: it holds a text in a column of
    numbers and texts in two columns of bytes, as an older version wrote
    them."""
    raw = at_schema(tmp_path / "seeded.db", 25)
    raw.executescript(SEED.read_text(encoding="utf-8"))
    raw.close()
    return Database(tmp_path / "seeded.db")


def test_every_column_whose_values_do_not_fit_is_named(seeded: Database) -> None:
    with seeded.view() as records:
        found = misfits(records)
    seeded.close()
    assert found == [
        Misfit("passkeys", "credential_id", 2),
        Misfit("passkeys", "credential", 2),
        Misfit("webhook_attempts", "events", 2),
    ]


def test_the_message_names_columns_and_counts_never_a_value(
    seeded: Database,
) -> None:
    with seeded.view() as records:
        values = {
            str(v)
            for table in ("passkeys", "webhook_attempts")
            for row in records.rows(table)
            for v in row
            if isinstance(v, str)
        }
        message = str(refused(misfits(records)))
    seeded.close()
    assert "webhook_attempts.events: 2" in message
    assert "passkeys.credential: 2" in message
    assert not [v for v in values if len(v) > 3 and v in message]


def test_a_database_this_version_wrote_fits(tmp_path: Path) -> None:
    db = Database(tmp_path / "new.db")
    with db.view() as records:
        assert misfits(records) == []
    db.close()
