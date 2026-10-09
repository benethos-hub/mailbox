"""The repository of TOTP devices: one contract, the same tests for the
in-memory and the SQLite implementation (docs/AUTHENTICATION.md 7)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryTotpRepository,
    Sealed,
    SqliteTotpRepository,
    SqliteUserRepository,
    StoredTotpDevice,
    TotpRepository,
)
from benethos_mailbox_service.errors import NotFoundError

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
SECRET = Sealed("key_1", b"nonce", b"secret 1")
PHONE = StoredTotpDevice("tfa_1", "Phone", SECRET, NOW)
TABLET = StoredTotpDevice(
    "tfa_2", "Tablet", Sealed("key_1", b"nonce", b"secret 2"), NOW + timedelta(1)
)


@pytest.fixture(params=["memory", "sqlite"])
def devices(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TotpRepository]:
    if request.param == "memory":
        yield InMemoryTotpRepository()
        return
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    for user_id in ("usr_a", "usr_b"):
        users.save(User(id=user_id, name=user_id))
    yield SqliteTotpRepository(db)
    db.close()


def test_devices_round_trip_oldest_first(devices: TotpRepository) -> None:
    assert devices.devices("usr_a") == []
    devices.add("usr_a", TABLET)
    devices.add("usr_a", PHONE)
    assert devices.devices("usr_a") == [PHONE, TABLET]
    assert devices.devices("usr_b") == []


def test_a_device_is_renamed(devices: TotpRepository) -> None:
    devices.add("usr_a", PHONE)
    devices.rename("usr_a", "tfa_1", "Old phone")
    assert [d.name for d in devices.devices("usr_a")] == ["Old phone"]
    with pytest.raises(NotFoundError):
        devices.rename("usr_b", "tfa_1", "Not mine")


def test_a_step_is_taken_once_per_device(devices: TotpRepository) -> None:
    assert devices.took("usr_a", "tfa_1", 100, NOW) is False
    devices.add("usr_a", PHONE)
    devices.add("usr_a", TABLET)
    assert devices.took("usr_a", "tfa_1", 100, LATER) is True
    assert devices.took("usr_a", "tfa_1", 100, LATER) is False
    assert devices.took("usr_a", "tfa_1", 99, LATER) is False
    # Each device keeps its own steps.
    assert devices.took("usr_a", "tfa_2", 100, LATER) is True
    assert devices.took("usr_b", "tfa_1", 101, LATER) is False
    phone = devices.devices("usr_a")[0]
    assert (phone.last_step, phone.last_used_at) == (100, LATER)


def test_a_device_is_removed_alone(devices: TotpRepository) -> None:
    devices.add("usr_a", PHONE)
    devices.add("usr_a", TABLET)
    assert devices.remove("usr_a", "tfa_1") is True
    assert devices.remove("usr_a", "tfa_1") is False
    assert devices.devices("usr_a") == [TABLET]


def test_every_device_of_a_user_goes_at_once(devices: TotpRepository) -> None:
    devices.add("usr_a", PHONE)
    devices.add("usr_a", TABLET)
    devices.add("usr_b", StoredTotpDevice("tfa_3", "Phone", SECRET, NOW))
    assert devices.remove_all("usr_a") is True
    assert devices.remove_all("usr_a") is False
    assert devices.devices("usr_a") == []
    assert len(devices.devices("usr_b")) == 1


def test_a_deleted_user_takes_its_devices_along(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="Anna"))
    devices = SqliteTotpRepository(db)
    devices.add("usr_a", PHONE)
    users.delete("usr_a")
    assert devices.devices("usr_a") == []
    db.close()
