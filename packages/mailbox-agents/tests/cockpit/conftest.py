"""The cockpit over a data folder of one state file."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_agents.cockpit.app import Cockpit, make_app

from .cockpit_helpers import NOW, SECRET, filled, mailbox


@pytest.fixture
def cockpit(tmp_path: Path) -> Cockpit:
    filled(tmp_path / "counting" / "counting.db")
    return Cockpit(data_dir=tmp_path, secret=SECRET, mailbox=mailbox, now=lambda: NOW)


@pytest.fixture
def client(cockpit: Cockpit) -> Iterator[TestClient]:
    with TestClient(make_app(cockpit), follow_redirects=False) as found:
        yield found
