"""The repository of second factors: one contract, the same tests for the
in-memory and the SQLite implementation (docs/AUTHENTICATION.md 6)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.storage import (
    Database,
    InMemorySecondFactorRepository,
    Sealed,
    SecondFactorRepository,
    SqliteSecondFactorRepository,
    SqliteUserRepository,
    StoredDevice,
)
from benethos_mailbox_service.errors import NotFoundError

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
PHONE = StoredDevice("tfa_1", "Phone", Sealed("key_1", b"nonce", b"secret 1"), NOW)
TABLET = StoredDevice(
    "tfa_2", "Tablet", Sealed("key_1", b"nonce", b"secret 2"), NOW + timedelta(1)
)


@pytest.fixture(params=["memory", "sqlite"])
def factors(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[SecondFactorRepository]:
    if request.param == "memory":
        yield InMemorySecondFactorRepository()
        return
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    for user_id in ("usr_a", "usr_b"):
        users.save(User(id=user_id, name=user_id))
    yield SqliteSecondFactorRepository(db)
    db.close()


def test_devices_round_trip_oldest_first(factors: SecondFactorRepository) -> None:
    assert factors.devices("usr_a") == []
    factors.add("usr_a", TABLET)
    factors.add("usr_a", PHONE)
    assert factors.devices("usr_a") == [PHONE, TABLET]
    assert factors.devices("usr_b") == []


def test_a_device_is_renamed(factors: SecondFactorRepository) -> None:
    factors.add("usr_a", PHONE)
    factors.rename("usr_a", "tfa_1", "Old phone")
    assert [d.name for d in factors.devices("usr_a")] == ["Old phone"]
    with pytest.raises(NotFoundError):
        factors.rename("usr_b", "tfa_1", "Not mine")


def test_a_step_is_taken_once_per_device(factors: SecondFactorRepository) -> None:
    assert factors.took("usr_a", "tfa_1", 100, NOW) is False
    factors.add("usr_a", PHONE)
    factors.add("usr_a", TABLET)
    assert factors.took("usr_a", "tfa_1", 100, LATER) is True
    assert factors.took("usr_a", "tfa_1", 100, LATER) is False
    assert factors.took("usr_a", "tfa_1", 99, LATER) is False
    # Each device keeps its own steps.
    assert factors.took("usr_a", "tfa_2", 100, LATER) is True
    assert factors.took("usr_b", "tfa_1", 101, LATER) is False
    phone = factors.devices("usr_a")[0]
    assert (phone.last_step, phone.last_used_at) == (100, LATER)


def test_a_device_is_removed_alone(factors: SecondFactorRepository) -> None:
    factors.add("usr_a", PHONE)
    factors.add("usr_a", TABLET)
    factors.replace_codes("usr_a", ["h1"])
    assert factors.remove("usr_a", "tfa_1") is True
    assert factors.remove("usr_a", "tfa_1") is False
    assert factors.devices("usr_a") == [TABLET]
    assert factors.codes_left("usr_a") == 1


def test_a_recovery_code_works_once(factors: SecondFactorRepository) -> None:
    factors.replace_codes("usr_a", ["h1", "h2"])
    assert factors.use_code("usr_a", "h1", NOW) is True
    assert factors.use_code("usr_a", "h1", NOW) is False
    assert factors.use_code("usr_a", "unknown", NOW) is False
    assert factors.use_code("usr_b", "h2", NOW) is False
    assert factors.codes_left("usr_a") == 1


def test_new_codes_replace_the_whole_set(factors: SecondFactorRepository) -> None:
    factors.replace_codes("usr_a", ["h1", "h2"])
    factors.use_code("usr_a", "h1", NOW)
    factors.replace_codes("usr_a", ["h3", "h4", "h5"])
    assert factors.codes_left("usr_a") == 3
    assert factors.use_code("usr_a", "h2", NOW) is False
    assert factors.use_code("usr_a", "h3", NOW) is True


def test_deleting_takes_every_device_and_the_codes(
    factors: SecondFactorRepository,
) -> None:
    factors.add("usr_a", PHONE)
    factors.add("usr_a", TABLET)
    factors.replace_codes("usr_a", ["h1"])
    factors.add("usr_b", StoredDevice("tfa_3", "Phone", PHONE.secret, NOW))
    assert factors.delete("usr_a") is True
    assert factors.delete("usr_a") is False
    assert factors.devices("usr_a") == [] and factors.codes_left("usr_a") == 0
    assert len(factors.devices("usr_b")) == 1


def test_a_deleted_user_takes_its_devices_along(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="Anna"))
    factors = SqliteSecondFactorRepository(db)
    factors.add("usr_a", PHONE)
    factors.replace_codes("usr_a", ["h1"])
    users.delete("usr_a")
    assert factors.devices("usr_a") == [] and factors.codes_left("usr_a") == 0
    db.close()
