"""The folders of messages by id, read without their content (``Places``):
Gmail from the labels, Microsoft from the parent folder, JMAP from the
mailboxes. A message that is not there is left out."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.providers import Places
from benethos_mailbox_service.data.providers.jmap import JmapProvider
from benethos_mailbox_service.data.providers.memory import MemoryProvider

from ...gmail_adapter import adapter as gmail_adapter
from ...gmail_fake import FakeGmail
from ...graph_fake import FakeGraph
from ...imap_fake import make_message
from ...jmap_fake import FakeJmap
from ...microsoft_adapter import adapter as microsoft_adapter


@pytest.fixture
def server() -> FakeJmap:
    return FakeJmap()


async def test_gmail_reads_the_folders_from_the_labels(gmail: FakeGmail) -> None:
    gmail.labels["Label_1"] = {"id": "Label_1", "name": "Invoices", "type": "user"}
    one = gmail.add_message(labels=("INBOX", "Label_1", "UNREAD"))
    trashed = gmail.add_message(labels=("TRASH", "Label_1"))
    provider = gmail_adapter(gmail)
    assert isinstance(provider, Places)
    found = await provider.folders_of([one, trashed, "0000000000000fff"])
    assert found == {one: ["INBOX", "Label_1", "ALL_MAIL"], trashed: ["TRASH"]}
    shapes = {
        r.url.params.get("format") for r in gmail.requests if "/messages/" in r.url.path
    }
    assert shapes == {"minimal"}


async def test_microsoft_reads_the_parent_folder(graph: FakeGraph) -> None:
    one = graph.add_message()
    provider = microsoft_adapter(graph)
    assert isinstance(provider, Places)
    found = await provider.folders_of([one, "AAMk404=", "not an id"])
    assert found == {one: [graph.well_known["inbox"]]}
    assert not [r for r in graph.requests if r.url.path.endswith("/$value")]


async def test_jmap_reads_the_mailboxes(jmap: JmapProvider, server: FakeJmap) -> None:
    one = server.add_email(make_message("One"))
    assert isinstance(jmap, Places)
    found = await jmap.folders_of([one, "Mmissing"])
    assert found == {one: ["inbox"]}


def test_the_memory_adapter_reads_whole_messages() -> None:
    assert not isinstance(MemoryProvider(), Places)
