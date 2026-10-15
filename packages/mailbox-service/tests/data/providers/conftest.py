"""Fixtures the tests of the adapters share."""

from __future__ import annotations

import pytest

from ...graph_fake import FakeGraph


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()
