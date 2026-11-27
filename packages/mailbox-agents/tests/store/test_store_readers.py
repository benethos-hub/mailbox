"""A reader of a state file beside or after its writer."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.errors import StateFileError
from benethos_mailbox_agents.store import Store, path_for

NOW = datetime(2026, 11, 27, tzinfo=UTC)


class _Refusing:
    """sqlite3.connect, failing the first call as a folder a reader may
    not write fails it for a file in WAL mode without its -shm."""

    def __init__(self) -> None:
        self.real = sqlite3.connect
        self.uris: list[str] = []

    def __call__(self, database: str, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        self.uris.append(database)
        if len(self.uris) == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return self.real(database, *args, **kwargs)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    path = path_for(tmp_path, "counting")
    with Store.open(path) as store:
        store.set_progress(NOW)
    return path


def test_a_reader_opens_a_cleanly_closed_file_as_immutable(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not path.with_name(path.name + "-wal").exists()
    refusing = _Refusing()
    monkeypatch.setattr(sqlite3, "connect", refusing)

    with Store.open(path, read_only=True) as reader:
        assert reader.progress() == NOW

    assert [uri.rsplit("?", 1)[1] for uri in refusing.uris] == [
        "mode=ro",
        "mode=ro&immutable=1",
    ]


def test_a_reader_beside_a_wal_does_not_try_again(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path.with_name(path.name + "-wal").write_bytes(b"")
    refusing = _Refusing()
    monkeypatch.setattr(sqlite3, "connect", refusing)

    with pytest.raises(StateFileError, match="unable to open"):
        Store.open(path, read_only=True)

    assert len(refusing.uris) == 1
