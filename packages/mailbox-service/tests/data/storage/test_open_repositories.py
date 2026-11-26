"""The one place that picks the store: each value of the setting by its
name, and none other."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from benethos_mailbox_service.data.storage import open_repositories
from benethos_mailbox_service.errors import StorageError


def test_an_unknown_storage_opens_nothing(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    with pytest.raises(StorageError, match="there is no storage elsewhere"):
        open_repositories(cast(Any, "elsewhere"), path)
    assert list(tmp_path.iterdir()) == []


def test_postgres_without_its_server_opens_nothing(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="needs the server"):
        open_repositories("postgres", tmp_path / "store.db")
    assert list(tmp_path.iterdir()) == []


def test_memory_and_sqlite_by_their_names(tmp_path: Path) -> None:
    memory = open_repositories("memory", tmp_path / "store.db")
    assert memory.store is None
    assert not (tmp_path / "store.db").exists()
    sqlite = open_repositories("sqlite", tmp_path / "store.db")
    try:
        assert sqlite.store is not None
        assert (tmp_path / "store.db").exists()
    finally:
        sqlite.close()
