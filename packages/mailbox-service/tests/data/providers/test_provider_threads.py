"""Threads as each adapter reads them: Gmail, JMAP and Microsoft keep
their own, IMAP reads the summaries the domain's index names."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.providers import (
    Capability,
    Summaries,
    Threads,
)
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.data.providers.microsoft import (
    messages as microsoft_messages,
)
from benethos_mailbox_service.errors import NotFoundError

from ... import gmail_adapter, jmap_adapter, microsoft_adapter
from ...gmail_fake import FakeGmail
from ...graph_fake import FakeGraph
from ...imap_adapter import provider
from ...imap_fake import FakeMailBox, make_message
from ...jmap_fake import FakeJmap

# --- Gmail ---------------------------------------------------------------------------


async def test_gmail_reads_a_thread_oldest_first() -> None:
    gmail = FakeGmail()
    first = gmail.add_message(subject="Hello")
    thread = gmail.messages[first]["threadId"]
    second = gmail.add_message(
        labels=("SENT",), thread=thread, subject="Re: Hello", sender="me@example.com"
    )
    gmail.add_message(subject="Other")
    adapter = gmail_adapter.adapter(gmail)
    assert isinstance(adapter, Threads)
    assert (await adapter.abilities()).has(Capability.THREADS)
    found = await adapter.thread_messages(thread, 500)
    assert [m.id for m in found.messages] == [first, second]
    assert "SENT" in found.messages[1].folder_ids
    assert all(m.thread_id == thread for m in found.messages)
    assert not found.truncated
    newest = await adapter.thread_messages(thread, 1)
    assert ([m.id for m in newest.messages], newest.truncated) == ([second], True)


@pytest.mark.parametrize("thread_id", ["00000000000000aa", "not an id"])
async def test_gmail_answers_a_missing_thread_as_not_found(thread_id: str) -> None:
    with pytest.raises(NotFoundError, match="thread"):
        await gmail_adapter.adapter(FakeGmail()).thread_messages(thread_id, 500)


# --- JMAP ----------------------------------------------------------------------------


async def test_jmap_reads_a_thread_by_its_emails() -> None:
    server = FakeJmap()
    first = server.add_email(make_message("Hello"), thread="T1")
    server.add_email(make_message("Other"))
    second = server.add_email(make_message("Re: Hello"), mailbox="sent", thread="T1")
    adapter = jmap_adapter.adapter(server)
    assert (await adapter.abilities()).has(Capability.THREADS)
    found = await adapter.thread_messages("T1", 500)
    assert [m.id for m in found.messages] == [first, second]
    assert [m.thread_id for m in found.messages] == ["T1", "T1"]
    assert not found.truncated
    newest = await adapter.thread_messages("T1", 1)
    assert ([m.id for m in newest.messages], newest.truncated) == ([second], True)


@pytest.mark.parametrize("thread_id", ["T9", "not an id!"])
async def test_jmap_answers_a_missing_thread_as_not_found(thread_id: str) -> None:
    with pytest.raises(NotFoundError, match="thread"):
        await jmap_adapter.adapter(FakeJmap()).thread_messages(thread_id, 500)


# --- Microsoft -----------------------------------------------------------------------


async def test_graph_reads_a_conversation_across_folders() -> None:
    graph = FakeGraph()
    later = graph.add_message("sentitems", conversationId="c'1", subject="Re: Hi")
    other = graph.add_message(conversationId="c2")
    first = graph.add_message(
        conversationId="c'1", receivedDateTime="2026-08-01T10:00:00Z"
    )
    adapter = microsoft_adapter.adapter(graph)
    assert (await adapter.abilities()).has(Capability.THREADS)
    found = await adapter.thread_messages("c'1", 500)
    assert [m.id for m in found.messages] == [first, later]
    assert other not in [m.id for m in found.messages]
    assert not found.truncated


async def test_graph_keeps_the_newest_of_a_long_conversation() -> None:
    graph = FakeGraph()
    ids = [graph.add_message(conversationId="long") for _ in range(5)]
    adapter = microsoft_adapter.adapter(graph)
    found = await adapter.thread_messages("long", 2)
    assert ([m.id for m in found.messages], found.truncated) == (ids[-2:], True)


async def test_graph_reads_every_page_up_to_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(microsoft_messages, "PAGE_SIZE", 2)
    graph = FakeGraph()
    ids = [graph.add_message(conversationId="paged") for _ in range(5)]
    found = await microsoft_adapter.adapter(graph).thread_messages("paged", 500)
    assert ([m.id for m in found.messages], found.truncated) == (ids, False)


async def test_graph_answers_a_missing_conversation_as_not_found() -> None:
    with pytest.raises(NotFoundError, match="thread"):
        await microsoft_adapter.adapter(FakeGraph()).thread_messages("none", 500)


# --- IMAP ----------------------------------------------------------------------------


async def test_imap_reads_summaries_in_any_folder(server: FakeMailBox) -> None:
    server.add("Sent", 4, make_message("Re: Invoice 1"))
    imap = provider(server)
    assert isinstance(imap, Summaries)
    assert not isinstance(imap, Threads)
    assert (await imap.abilities()).has(Capability.THREADS)
    wanted = [
        mappers.message_id("INBOX", 7, 1),
        mappers.message_id("Sent", 1, 4),
        mappers.message_id("INBOX", 7, 99),  # gone
        mappers.message_id("INBOX", 6, 2),  # renumbered
    ]
    found = await imap.summaries(wanted)
    assert set(found) == set(wanted[:2])
    assert found[wanted[1]].subject == "Re: Invoice 1"
    assert found[wanted[1]].folder_ids == [mappers.folder_id("Sent")]
