"""What a JMAP account can do follows from its session and its folders
(docs/UNIFORM.md, rule R4): sending from the server's submission and a
folder to send from, push from its event source."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import Capability, Mark

from ...jmap_fake import FakeJmap
from .test_jmap import adapter


@pytest.fixture
def server() -> FakeJmap:
    return FakeJmap()


async def test_a_full_server(server: FakeJmap) -> None:
    found = await adapter(server).abilities()
    assert set(found.capabilities) == set(Capability) - {Capability.REFUSED}
    assert found.marks.written == sorted(Mark)


async def test_without_submission_it_cannot_send(server: FakeJmap) -> None:
    del server.capabilities["urn:ietf:params:jmap:submission"]
    found = await adapter(server).abilities()
    assert not {Capability.SEND, Capability.SENT_COPY} & set(found.capabilities)


async def test_without_an_event_source_it_is_polled(server: FakeJmap) -> None:
    server.event_source = False
    found = await adapter(server).abilities()
    assert Capability.PUSH not in found.capabilities


async def test_the_folders_it_lacks(server: FakeJmap) -> None:
    for role in ("drafts", "sent", "trash"):
        del server.mailboxes[role]
    found = await adapter(server).abilities()
    # Nowhere to keep a draft or a copy, or to send from.
    assert not {
        Capability.DRAFTS,
        Capability.SEND,
        Capability.SENT_COPY,
        Capability.TRASH,
    } & set(found.capabilities)
