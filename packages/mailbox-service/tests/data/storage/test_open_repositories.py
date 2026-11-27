"""The one place that picks the store: each value of the setting by its
name, and none other, and the oldest server it takes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import pytest

from benethos_mailbox_common.storage.server_place import supported
from benethos_mailbox_service.data.storage import Server, open_repositories
from benethos_mailbox_service.errors import STORAGE_ERRORS, StorageError


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


@pytest.mark.parametrize(
    ("version", "refused"),
    [(180004, True), (189999, True), (190000, False), (200001, False)],
    ids=["18.4", "18.9999", "19.0", "20.1"],
)
def test_a_server_older_than_19_is_refused(version: int, refused: bool) -> None:
    if refused:
        with pytest.raises(StorageError, match="needs PostgreSQL 19.0 or newer"):
            supported(version, STORAGE_ERRORS)
    else:
        supported(version, STORAGE_ERRORS)


def test_without_its_driver_postgres_names_the_extra(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "psycopg", None)
    server = Server(
        host="db.example.org",
        port=5432,
        database="mailbox",
        role="svc",
        password="unused",  # pragma: allowlist secret
    )
    with pytest.raises(StorageError, match=r"benethos-mailbox-service\[postgres\]"):
        open_repositories("postgres", tmp_path / "store.db", server)
