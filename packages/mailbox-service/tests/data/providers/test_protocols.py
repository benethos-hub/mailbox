"""What each adapter may do beyond reading, as its protocols say: an
adapter implements those it may be able to do and no other. What its
account can do it answers from the server (``abilities``)."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.providers import (
    Deletes,
    Deltas,
    Drafts,
    Sends,
    Watches,
    Writes,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider
from benethos_mailbox_service.data.providers.jmap import JmapProvider
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider
from benethos_mailbox_service.data.providers.pop3 import Pop3Provider

PROTOCOLS = (Deletes, Writes, Drafts, Sends, Watches, Deltas)
EVERY = set(PROTOCOLS)

ADAPTERS = [
    (ImapProvider, EVERY - {Deltas}),
    (JmapProvider, EVERY),
    (MicrosoftProvider, EVERY - {Watches}),
    (MemoryProvider, EVERY - {Watches, Deltas}),
    (Pop3Provider, {Deletes, Sends}),
]


@pytest.mark.parametrize(("adapter", "able"), ADAPTERS, ids=lambda a: str(a))
def test_each_adapter_implements_what_it_can(adapter: type, able: set[type]) -> None:
    assert {p for p in PROTOCOLS if issubclass(adapter, p)} == able


@pytest.mark.parametrize(("adapter", "able"), ADAPTERS, ids=lambda a: str(a))
def test_each_adapter_says_whether_its_ids_stay(adapter: type, able: set[type]) -> None:
    # IMAP and POP3 ids name a place, and the domain maps them.
    assert adapter.stable_ids is (adapter not in (ImapProvider, Pop3Provider))
