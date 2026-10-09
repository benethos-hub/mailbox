"""The repository of recovery codes: one contract, the same tests for the
in-memory and the SQLite implementation (docs/AUTHENTICATION.md 6)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryRecoveryCodeRepository,
    RecoveryCodeRepository,
    SqliteRecoveryCodeRepository,
    SqliteUserRepository,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def codes(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[RecoveryCodeRepository]:
    if request.param == "memory":
        yield InMemoryRecoveryCodeRepository()
        return
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    for user_id in ("usr_a", "usr_b"):
        users.save(User(id=user_id, name=user_id))
    yield SqliteRecoveryCodeRepository(db)
    db.close()


def test_a_recovery_code_works_once(codes: RecoveryCodeRepository) -> None:
    codes.replace("usr_a", ["h1", "h2"])
    assert codes.use("usr_a", "h1", NOW) is True
    assert codes.use("usr_a", "h1", NOW) is False
    assert codes.use("usr_a", "unknown", NOW) is False
    assert codes.use("usr_b", "h2", NOW) is False
    assert codes.left("usr_a") == 1


def test_new_codes_replace_the_whole_set(codes: RecoveryCodeRepository) -> None:
    codes.replace("usr_a", ["h1", "h2"])
    codes.use("usr_a", "h1", NOW)
    codes.replace("usr_a", ["h3", "h4", "h5"])
    assert codes.left("usr_a") == 3
    assert codes.use("usr_a", "h2", NOW) is False
    assert codes.use("usr_a", "h3", NOW) is True


def test_deleting_takes_the_codes_of_one_user(codes: RecoveryCodeRepository) -> None:
    codes.replace("usr_a", ["h1"])
    codes.replace("usr_b", ["h1"])
    codes.delete("usr_a")
    assert codes.left("usr_a") == 0 and codes.left("usr_b") == 1


def test_a_deleted_user_takes_its_codes_along(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="Anna"))
    codes = SqliteRecoveryCodeRepository(db)
    codes.replace("usr_a", ["h1"])
    users.delete("usr_a")
    assert codes.left("usr_a") == 0
    db.close()
