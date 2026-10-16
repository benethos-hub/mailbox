"""Fixtures the tests of the adapters share."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.providers.jmap import JmapProvider

from ...gmail_fake import FakeGmail
from ...graph_fake import FakeGraph
from ...jmap_adapter import adapter
from ...jmap_fake import FakeJmap


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def gmail() -> FakeGmail:
    return FakeGmail()


@pytest.fixture
def jmap(server: FakeJmap) -> JmapProvider:
    """The JMAP adapter on the module's ``server``, a fake JMAP server."""
    return adapter(server)
