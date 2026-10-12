"""Threads the index keeps for IMAP: through the real adapter against a
fake server, across folders, merged, and filled in for entries from
before threads."""

from __future__ import annotations

from dataclasses import replace

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import MessageUpdate
from benethos_mailbox_service.data.providers import ThreadHeaders
from benethos_mailbox_service.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_service.data.storage import InMemoryMessageIndexRepository
from benethos_mailbox_service.domain.sync import threads
from benethos_mailbox_service.domain.sync.passes import chain
from benethos_mailbox_service.errors import ProviderUnavailableError

from ...conftest import ADMIN
from ...imap_fake import FakeFolder, FakeMailBox, make_message

SENT = mappers.folder_id("Sent")


def header(subject: str) -> str:
    return f"<{abs(hash(subject))}@example.com>"


def answer(subject: str, *to: str) -> bytes:
    """A reply to the messages with these subjects, the last one answered."""
    return make_message(
        subject,
        extra_headers={
            "In-Reply-To": header(to[-1]),
            "References": " ".join(header(s) for s in to),
        },
    )


@pytest.fixture
def conversation(imap_server: FakeMailBox) -> FakeMailBox:
    """Mail 1 in the inbox, the answer to it in Sent, and the answer to
    that in the inbox again."""
    imap_server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    imap_server.add("Sent", 1, answer("Re: Mail 1", "Mail 1"))
    imap_server.add("INBOX", 5, answer("Re: Re: Mail 1", "Mail 1", "Re: Mail 1"))
    return imap_server


async def threads_by_subject(
    services: Services, account_id: str, folder_id: str | None = None
) -> dict[str, str | None]:
    page = await services.mailbox.list_messages(
        ADMIN, account_id, folder_id=folder_id, limit=50, cursor=None
    )
    return {m.subject or "": m.thread_id for m in page.items}


async def every_thread(services: Services, account_id: str) -> dict[str, str | None]:
    return {
        **await threads_by_subject(services, account_id),
        **await threads_by_subject(services, account_id, SENT),
    }


async def unavailable(*args: object) -> dict[str, ThreadHeaders]:
    raise ProviderUnavailableError("the server does not answer")


def updated(services: Services, account_id: str) -> list[str]:
    return [
        e.record.id
        for e in services.sync.feed.after([account_id], 0, limit=100)
        if e.record.type == "message.updated"
    ]


# --- pure ---------------------------------------------------------------------------


def test_the_chain_keeps_the_last_references_and_the_answered_one() -> None:
    headers = ThreadHeaders("<5@x>", "<9@x>", ("<1@x>", "<2@x>", "<3@x>", "<4@x>"))
    assert chain("msg_1", headers, 2).headers == ("<5@x>", "<3@x>", "<4@x>", "<9@x>")
    assert chain("msg_1", headers, 0).headers == ("<5@x>", "<9@x>")
    assert chain("msg_1", ThreadHeaders(), 20).headers == ()
    twice = ThreadHeaders("<2@x>", "<1@x>", ("<1@x>",))
    assert chain("msg_2", twice, 20).headers == ("<2@x>", "<1@x>")


# --- through the services -------------------------------------------------------------


async def test_a_conversation_across_folders_is_one_thread(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    found = await every_thread(imap_services, imap_account_id)
    conversation_threads = {
        found["Mail 1"],
        found["Re: Mail 1"],
        found["Re: Re: Mail 1"],
    }
    assert len(conversation_threads) == 1
    [thread] = conversation_threads
    assert thread is not None and thread.startswith("thr_")
    others = {found[f"Mail {n}"] for n in (2, 3, 4)}
    assert len(others) == 3 and thread not in others


async def test_a_listing_before_any_sync_threads_at_once(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    found = await every_thread(imap_services, imap_account_id)
    assert found["Mail 1"] is not None
    assert found["Mail 1"] == found["Re: Re: Mail 1"] == found["Re: Mail 1"]


async def test_a_message_and_a_change_name_their_thread(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    page = await imap_services.mailbox.list_messages(
        ADMIN, imap_account_id, folder_id=SENT, limit=5, cursor=None
    )
    [reply] = page.items
    message = await imap_services.mailbox.get_message(ADMIN, imap_account_id, reply.id)
    assert message.thread_id == reply.thread_id is not None
    changed = await imap_services.mailbox.update_message(
        ADMIN, imap_account_id, reply.id, MessageUpdate(starred=True)
    )
    assert changed.thread_id == reply.thread_id


async def test_a_move_keeps_the_thread(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    before = await threads_by_subject(imap_services, imap_account_id)
    conversation.other_client_moves("INBOX", 1, "Archive", 1)
    await imap_services.sync.sync_account(imap_account_id)
    after = await threads_by_subject(
        imap_services, imap_account_id, mappers.folder_id("Archive")
    )
    assert after["Mail 1"] == before["Mail 1"]


async def test_a_late_message_merges_two_threads_into_the_older(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    before = await threads_by_subject(imap_services, imap_account_id)
    imap_server.add("INBOX", 6, answer("Both", "Mail 1", "Mail 2"))
    await imap_services.sync.sync_account(imap_account_id)
    after = await threads_by_subject(imap_services, imap_account_id)
    assert after["Both"] == after["Mail 1"] == after["Mail 2"] == before["Mail 1"]
    # Mail 2 changed its thread: the feed says so. Both is new.
    ids = {
        m.subject: m.id
        for m in (
            await imap_services.mailbox.list_messages(
                ADMIN, imap_account_id, folder_id=None, limit=50, cursor=None
            )
        ).items
    }
    assert updated(imap_services, imap_account_id) == [ids["Mail 2"]]


async def test_the_first_sync_reports_no_merge(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    imap_server.add("INBOX", 6, answer("Both", "Mail 1", "Mail 2"))
    await imap_services.sync.sync_account(imap_account_id)
    assert updated(imap_services, imap_account_id) == []


async def test_entries_from_before_threads_are_threaded_a_portion_a_pass(
    imap_services: Services,
    imap_account_id: str,
    conversation: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    index = imap_services.index
    assert isinstance(index, InMemoryMessageIndexRepository)
    # As after the migration: the entries have no thread yet.
    own = index._entries[imap_account_id]
    for message_id, entry in own.items():
        own[message_id] = replace(entry, thread_id=None)
    index._links.clear()
    monkeypatch.setattr(threads, "THREADED_PER_PASS", 4)
    await imap_services.sync.sync_account(imap_account_id)
    assert len(index.unthreaded(imap_account_id, 10)) == 2
    await imap_services.sync.sync_account(imap_account_id)
    assert index.unthreaded(imap_account_id, 10) == []
    found = await every_thread(imap_services, imap_account_id)
    assert found["Mail 1"] == found["Re: Mail 1"] == found["Re: Re: Mail 1"]


async def test_a_failed_read_of_headers_waits_for_the_next_pass(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    index = imap_services.index
    assert isinstance(index, InMemoryMessageIndexRepository)
    own = index._entries[imap_account_id]
    for message_id, entry in own.items():
        own[message_id] = replace(entry, thread_id=None)
    with monkeypatch.context() as patched:
        patched.setattr(ImapProvider, "message_headers", unavailable)
        await imap_services.sync.sync_account(imap_account_id)
    assert len(index.unthreaded(imap_account_id, 10)) == 4
    await imap_services.sync.sync_account(imap_account_id)
    assert index.unthreaded(imap_account_id, 10) == []


async def test_the_references_kept_follow_the_setting(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    """With none kept, a reply finds its thread through In-Reply-To only."""
    imap_services.sync._threads._references = 0
    imap_server.add("INBOX", 6, answer("Late", "Mail 1", "Mail 2"))
    await imap_services.sync.sync_account(imap_account_id)
    found = await threads_by_subject(imap_services, imap_account_id)
    assert found["Late"] == found["Mail 2"] != found["Mail 1"]
