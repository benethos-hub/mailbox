"""The repository of passkeys: one contract, the same tests for the
in-memory and the SQLite implementation (docs/AUTHENTICATION.md 7)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryPasskeyRepository,
    PasskeyRepository,
    SqlitePasskeyRepository,
    SqliteUserRepository,
    StoredPasskey,
)
from benethos_mailbox_service.errors import ConflictError, NotFoundError

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
LAPTOP = StoredPasskey("psk_1", "Laptop", b"cred-1", b"data 1", NOW, sign_count=3)
KEY = StoredPasskey("psk_2", "Security key", b"cred-2", b"data 2", NOW + timedelta(1))


@pytest.fixture(params=["memory", "sqlite"])
def passkeys(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[PasskeyRepository]:
    if request.param == "memory":
        yield InMemoryPasskeyRepository()
        return
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    for user_id in ("usr_a", "usr_b"):
        users.save(User(id=user_id, name=user_id))
    yield SqlitePasskeyRepository(db)
    db.close()


def test_passkeys_round_trip_oldest_first(passkeys: PasskeyRepository) -> None:
    assert passkeys.passkeys("usr_a") == []
    passkeys.add("usr_a", KEY)
    passkeys.add("usr_a", LAPTOP)
    assert passkeys.passkeys("usr_a") == [LAPTOP, KEY]
    assert passkeys.passkeys("usr_b") == []


def test_a_credential_is_stored_once_across_users(
    passkeys: PasskeyRepository,
) -> None:
    passkeys.add("usr_a", LAPTOP)
    with pytest.raises(ConflictError, match="stored already"):
        passkeys.add("usr_b", StoredPasskey("psk_3", "Copy", b"cred-1", b"x", NOW))
    assert passkeys.passkeys("usr_b") == []


def test_a_passkey_is_renamed(passkeys: PasskeyRepository) -> None:
    passkeys.add("usr_a", LAPTOP)
    passkeys.rename("usr_a", "psk_1", "Old laptop")
    assert [p.name for p in passkeys.passkeys("usr_a")] == ["Old laptop"]
    with pytest.raises(NotFoundError):
        passkeys.rename("usr_b", "psk_1", "Not mine")


def test_a_signature_counts_once_and_only_upwards(
    passkeys: PasskeyRepository,
) -> None:
    passkeys.add("usr_a", LAPTOP)
    assert not passkeys.used("usr_a", "psk_1", 3, LATER)
    assert not passkeys.used("usr_a", "psk_1", 2, LATER)
    assert passkeys.used("usr_a", "psk_1", 4, LATER)
    assert not passkeys.used("usr_a", "psk_1", 4, LATER)
    assert not passkeys.used("usr_b", "psk_1", 9, LATER)
    [stored] = passkeys.passkeys("usr_a")
    assert (stored.sign_count, stored.last_used_at) == (4, LATER)


def test_a_passkey_without_a_counter_signs_each_time(
    passkeys: PasskeyRepository,
) -> None:
    passkeys.add("usr_a", KEY)
    assert passkeys.used("usr_a", "psk_2", 0, NOW)
    assert passkeys.used("usr_a", "psk_2", 0, LATER)
    assert passkeys.used("usr_a", "psk_2", 1, LATER)
    # Once it counted, a zero is a copy of the key or a reset one.
    assert not passkeys.used("usr_a", "psk_2", 0, LATER)


def test_passkeys_are_removed(passkeys: PasskeyRepository) -> None:
    passkeys.add("usr_a", LAPTOP)
    passkeys.add("usr_a", KEY)
    assert not passkeys.remove("usr_b", "psk_1")
    assert passkeys.remove("usr_a", "psk_1")
    assert not passkeys.remove("usr_a", "psk_1")
    assert passkeys.remove_all("usr_a")
    assert not passkeys.remove_all("usr_a")
    assert passkeys.passkeys("usr_a") == []


def test_passkeys_go_with_their_user(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="a"))
    repository = SqlitePasskeyRepository(db)
    repository.add("usr_a", LAPTOP)
    users.delete("usr_a")
    assert repository.passkeys("usr_a") == []
    db.close()
