"""Fixtures the tests of the storage share."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import Account, ProviderType
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryMessageIndexRepository,
    MessageIndexRepository,
    SqliteAccountRepository,
    SqliteMessageIndexRepository,
)

from .index_helpers import ACC


@pytest.fixture(params=["memory", "sqlite"])
def index(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[MessageIndexRepository]:
    if request.param == "memory":
        yield InMemoryMessageIndexRepository()
        return
    db = Database(tmp_path / "index.db")
    accounts = SqliteAccountRepository(db)
    for account_id in (ACC, "acc_2"):
        accounts.add(
            Account(id=account_id, provider=ProviderType.IMAP, email="a@example.com")
        )
    yield SqliteMessageIndexRepository(db)
    db.close()
