"""The repository of second factors: one contract, the same tests for the
in-memory and the SQLite implementation (docs/AUTHENTICATION.md 6)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
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
    StoredFactor,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
SECRET = Sealed("key_1", b"nonce", b"sealed secret")
FACTOR = StoredFactor(SECRET, NOW)


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


def test_a_factor_round_trips(factors: SecondFactorRepository) -> None:
    assert factors.get("usr_a") is None
    factors.set("usr_a", FACTOR, ["h1", "h2"])
    assert factors.get("usr_a") == FACTOR
    assert factors.codes_left("usr_a") == 2
    assert factors.get("usr_b") is None and factors.codes_left("usr_b") == 0


def test_a_new_factor_replaces_the_old_and_its_codes(
    factors: SecondFactorRepository,
) -> None:
    factors.set("usr_a", FACTOR, ["h1", "h2"])
    factors.took("usr_a", 100)
    fresh = StoredFactor(Sealed("key_1", b"other", b"other secret"), NOW)
    factors.set("usr_a", fresh, ["h3"])
    assert factors.get("usr_a") == fresh
    assert factors.use_code("usr_a", "h1", NOW) is False
    assert factors.codes_left("usr_a") == 1


def test_a_step_is_taken_once_and_never_an_earlier_one(
    factors: SecondFactorRepository,
) -> None:
    assert factors.took("usr_a", 100) is False
    factors.set("usr_a", FACTOR, [])
    assert factors.took("usr_a", 100) is True
    assert factors.took("usr_a", 100) is False
    assert factors.took("usr_a", 99) is False
    assert factors.took("usr_a", 101) is True
    stored = factors.get("usr_a")
    assert stored is not None and stored.last_step == 101


def test_a_recovery_code_works_once(factors: SecondFactorRepository) -> None:
    factors.set("usr_a", FACTOR, ["h1", "h2"])
    assert factors.use_code("usr_a", "h1", NOW) is True
    assert factors.use_code("usr_a", "h1", NOW) is False
    assert factors.use_code("usr_a", "unknown", NOW) is False
    assert factors.use_code("usr_b", "h2", NOW) is False
    assert factors.codes_left("usr_a") == 1


def test_new_codes_replace_the_whole_set(factors: SecondFactorRepository) -> None:
    factors.set("usr_a", FACTOR, ["h1", "h2"])
    factors.use_code("usr_a", "h1", NOW)
    factors.replace_codes("usr_a", ["h3", "h4", "h5"])
    assert factors.codes_left("usr_a") == 3
    assert factors.use_code("usr_a", "h2", NOW) is False
    assert factors.use_code("usr_a", "h3", NOW) is True


def test_deleting_takes_the_factor_and_its_codes(
    factors: SecondFactorRepository,
) -> None:
    factors.set("usr_a", FACTOR, ["h1"])
    factors.set("usr_b", FACTOR, ["h1"])
    assert factors.delete("usr_a") is True
    assert factors.delete("usr_a") is False
    assert factors.get("usr_a") is None and factors.codes_left("usr_a") == 0
    assert factors.get("usr_b") == FACTOR and factors.codes_left("usr_b") == 1


def test_a_deleted_user_takes_its_factor_along(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="Anna"))
    factors = SqliteSecondFactorRepository(db)
    factors.set("usr_a", FACTOR, ["h1"])
    users.delete("usr_a")
    assert factors.get("usr_a") is None and factors.codes_left("usr_a") == 0
    db.close()
