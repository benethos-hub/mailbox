"""The failures of PostgreSQL as this project's errors, never with a value
of a row: the server's text of a violated key quotes the key, and the
first line of other failures can quote a value."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.models import ApiToken, User
from benethos_mailbox_service.data.storage import Database, repositories_on
from benethos_mailbox_service.data.storage.sql.schema import keys
from benethos_mailbox_service.errors import ConflictError, StorageError

from ..postgres_helpers import database, schema

# What SQLAlchemy would add: the statement and its parameters.
SQLALCHEMY_TEXT = ("[SQL:", "[parameters:", "Background on this error")


@pytest.fixture
def db() -> Iterator[Database]:
    with schema() as name:
        opened = database(name)
        yield opened
        opened.close()


def _plain(message: str, *values: str) -> None:
    for part in (*SQLALCHEMY_TEXT, *values):
        assert part not in message


def test_a_conflict_names_the_constraint_and_no_value(db: Database) -> None:
    stores = repositories_on(db)
    stores.users.save(User(id="usr_1", name="Someone"))
    with pytest.raises(ConflictError) as user:
        stores.users.save(User(id="usr_2", name="someone"))
    assert str(user.value).startswith("conflicts with a stored record: ")
    assert "users" in str(user.value)
    _plain(str(user.value), "Someone", "someone", "DETAIL")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    first = ApiToken(
        id="tok_1", user_id="usr_1", name="t", token_hash="hash-1", created_at=now
    )
    stores.tokens.save(first)
    with pytest.raises(ConflictError) as token:
        stores.tokens.save(first.model_copy(update={"id": "tok_2"}))
    assert "tokens" in str(token.value)
    _plain(str(token.value), "hash-1", "DETAIL")


def test_a_text_in_a_column_of_numbers_names_no_value(db: Database) -> None:
    """The first line of the server quotes the value it could not read."""
    attempts = sa.table("webhook_attempts", sa.column("events"))
    with pytest.raises(StorageError) as caught, db.connected() as conn:
        conn.execute(sa.insert(attempts).values(events="looked-for-5"))
    assert str(caught.value).startswith("the database failed: ")
    _plain(str(caught.value), "looked-for-5")


def test_a_text_bound_to_a_column_of_bytes_is_a_storage_error(db: Database) -> None:
    """The driver refuses it before the server sees it, not as an error
    of the database."""
    unfit = keys.insert().values(key_id="k1", nonce="text-value", ciphertext=b"")
    with pytest.raises(StorageError) as caught, db.connected() as conn:
        conn.execute(unfit)
    _plain(str(caught.value), "text-value", "k1")
