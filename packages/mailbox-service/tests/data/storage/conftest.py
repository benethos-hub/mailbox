"""Fixtures the tests of the storage share. The settings a test turns,
such as the size of a chunk, are turned here alone: a test does not know
the module that holds them."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import Account, ProviderType
from benethos_mailbox_service.data.storage import (
    MessageIndexRepository,
    Repositories,
)
from benethos_mailbox_service.data.storage.sql import database, dialect
from benethos_mailbox_service.data.storage.sqlite import file

from .disk_helpers import Disk
from .index_helpers import ACC


@pytest.fixture
def index(repositories: Repositories) -> MessageIndexRepository:
    for account_id in (ACC, "acc_2"):
        repositories.accounts.add(
            Account(id=account_id, provider=ProviderType.IMAP, email="a@example.com")
        )
    return repositories.index


@pytest.fixture
def disk() -> Iterator[Disk]:
    made = Disk()
    yield made
    made.mend()


@pytest.fixture
def in_chunks(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Sets how many values one ``IN`` of the database takes at most."""

    def size(values: int) -> None:
        monkeypatch.setattr(dialect, "IN_CHUNK", values)

    return size


@pytest.fixture
def export_chunks(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Sets how many rows of a table the export reads at once."""

    def size(rows: int) -> None:
        monkeypatch.setattr(database, "ROWS_CHUNK", rows)

    return size


@pytest.fixture
def no_room_for_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A disk on which the copy of a database before a migration cannot
    be made."""

    def full(path: Path, data: bytes = b"") -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(file, "create_private", full)
