"""Threads through the mailbox service: one with its messages, the threads
of a folder, under the grants' folders. IMAP from the index, JMAP from the
server, POP3 without."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Address, Grant, MessageSummary
from benethos_mailbox_service.data.providers import ThreadMessages
from benethos_mailbox_service.data.providers.jmap import JmapProvider
from benethos_mailbox_service.data.storage import InMemoryMessageIndexRepository
from benethos_mailbox_service.domain.mailbox.threads import thread_of
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    ForbiddenError,
    NotFoundError,
    NotSupportedError,
    ProviderUnavailableError,
)

from ...conftest import ADMIN, admin_bearer
from ...imap_fake import FakeFolder, FakeMailBox, make_message
from ...jmap_fake import FakeJmap
from ..thread_helpers import INBOX, SENT, answer, every_thread, synced


@pytest.fixture
def conversation(imap_server: FakeMailBox) -> FakeMailBox:
    """Mail 1 in the inbox, the answer in Sent, its answer in the inbox,
    and a thread of its own in the archive."""
    imap_server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    imap_server.add("Sent", 1, answer("Re: Mail 1", 10, "Mail 1"))
    imap_server.add("INBOX", 5, answer("Re: Re: Mail 1", 11, "Mail 1", "Re: Mail 1"))
    imap_server.add("Archive", 1, make_message("Kept"))
    return imap_server


def reading(account_id: str, *folders: str) -> Access:
    return Access(
        "u",
        "u",
        [
            Grant(
                accounts=[account_id],
                allow=["get_thread", "list_threads"],
                folders=list(folders),
            )
        ],
    )


# --- one thread ----------------------------------------------------------------------


async def test_an_imap_thread_across_folders_oldest_first(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    threads = await synced(imap_services, imap_account_id)
    thread = await imap_services.mailbox.get_thread(
        ADMIN, imap_account_id, threads["Mail 1"]
    )
    assert [m.subject for m in thread.messages] == [
        "Mail 1",
        "Re: Mail 1",
        "Re: Re: Mail 1",
    ]
    assert all(m.id.startswith("msg_") for m in thread.messages)
    assert {m.thread_id for m in thread.messages} == {thread.id}
    assert (thread.subject, thread.message_count) == ("Re: Re: Mail 1", 3)
    assert thread.unread_count == 3
    assert thread.date == datetime(2026, 9, 11, tzinfo=UTC)
    assert thread.folder_ids == [INBOX, SENT]
    # The account's own address me@example.com is left out.
    assert [p.email for p in thread.participants] == ["alice@example.com"]
    assert not thread.truncated


async def test_a_long_thread_lists_its_newest(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    threads = await synced(imap_services, imap_account_id)
    imap_services.mailbox._threads._limit = 2
    thread = await imap_services.mailbox.get_thread(
        ADMIN, imap_account_id, threads["Mail 1"]
    )
    assert [m.subject for m in thread.messages] == ["Re: Mail 1", "Re: Re: Mail 1"]
    assert thread.truncated


async def test_an_unknown_thread_is_not_found(
    imap_services: Services, imap_account_id: str
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    with pytest.raises(NotFoundError, match="thread thr_none"):
        await imap_services.mailbox.get_thread(ADMIN, imap_account_id, "thr_none")


async def test_a_grant_on_folders_sees_the_messages_in_them(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    threads = await synced(imap_services, imap_account_id)
    inbox_only = reading(imap_account_id, "inbox")
    thread = await imap_services.mailbox.get_thread(
        inbox_only, imap_account_id, threads["Mail 1"]
    )
    assert [m.subject for m in thread.messages] == ["Mail 1", "Re: Re: Mail 1"]
    assert thread.folder_ids == [INBOX]
    # Nothing of this thread is in the inbox.
    with pytest.raises(NotFoundError):
        await imap_services.mailbox.get_thread(
            inbox_only, imap_account_id, threads["Kept"]
        )


async def test_the_right_is_needed(
    imap_services: Services, imap_account_id: str
) -> None:
    other = Access("u", "u", [Grant(accounts=[imap_account_id], allow=["get_message"])])
    with pytest.raises(ForbiddenError, match="get_thread"):
        await imap_services.mailbox.get_thread(other, imap_account_id, "thr_x")


async def test_pop3_keeps_no_threads(
    pop3_services: Services, pop3_account_id: str
) -> None:
    with pytest.raises(NotSupportedError, match="threads"):
        await pop3_services.mailbox.get_thread(ADMIN, pop3_account_id, "thr_x")
    # Its inbox by threads as well, not an empty page.
    with pytest.raises(NotSupportedError, match="threads"):
        await pop3_services.mailbox.list_threads(
            ADMIN, pop3_account_id, folder_id="inbox", limit=20, cursor=None
        )


async def test_a_jmap_thread_comes_from_the_server(
    jmap_services: Services, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    first = jmap_server.add_email(make_message("Hello"), thread="T1")
    second = jmap_server.add_email(
        make_message("Re: Hello"), mailbox="sent", thread="T1"
    )
    thread = await jmap_services.mailbox.get_thread(ADMIN, jmap_account_id, "T1")
    assert [m.id for m in thread.messages] == [first, second]
    assert thread.account_id == jmap_account_id
    assert all(m.account_id == jmap_account_id for m in thread.messages)
    page = await jmap_services.mailbox.list_threads(
        ADMIN, jmap_account_id, folder_id="inbox", limit=10, cursor=None
    )
    assert "T1" in [t.id for t in page.items]


# --- the threads of a folder ---------------------------------------------------------


async def test_the_threads_of_a_folder_page_by_page(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    threads = await synced(imap_services, imap_account_id)
    mailbox = imap_services.mailbox
    first = await mailbox.list_threads(
        ADMIN, imap_account_id, folder_id="inbox", limit=2, cursor=None
    )
    assert [t.id for t in first.items] == [threads["Mail 1"], threads["Mail 4"]]
    assert first.items[0].message_count == 3
    assert first.items[0].subject == "Re: Re: Mail 1"
    shown = [t.id for t in first.items]
    cursor = first.next_cursor
    while cursor:
        page = await mailbox.list_threads(
            ADMIN, imap_account_id, folder_id="inbox", limit=2, cursor=cursor
        )
        shown += [t.id for t in page.items]
        cursor = page.next_cursor
    # Mail 1 on the last page belongs to a thread shown on the first.
    assert shown == [threads[f"Mail {n}"] for n in (1, 4, 3, 2)]


@pytest.mark.parametrize("folder", ["inbox", "all"])
@pytest.mark.parametrize("limit", [1, 2, 3])
async def test_each_thread_once_page_by_page(
    imap_services: Services,
    imap_account_id: str,
    conversation: FakeMailBox,
    folder: str,
    limit: int,
) -> None:
    """In the folder all too, whose id no message carries."""
    threads = await synced(imap_services, imap_account_id)
    shown = await every_thread(imap_services, imap_account_id, folder, limit)
    assert len(shown) == len(set(shown))
    wanted = {threads[f"Mail {n}"] for n in (1, 2, 3, 4)}
    if folder == "all":
        wanted.add(threads["Kept"])
    assert set(shown) == wanted


async def test_a_thread_in_the_last_second_of_a_page_shows_once(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    """Mail 2 and its answer came in the same second, one on each page."""
    imap_server.add("INBOX", 6, answer("Re: Mail 2", 2, "Mail 2"))
    await imap_services.sync.sync_account(imap_account_id)
    shown = await every_thread(imap_services, imap_account_id, "inbox", 4)
    assert len(shown) == len(set(shown)) == 4


async def test_an_imap_list_reads_every_thread_in_one_go(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    await synced(imap_services, imap_account_id)
    conversation.calls.clear()
    page = await imap_services.mailbox.list_threads(
        ADMIN, imap_account_id, folder_id="inbox", limit=50, cursor=None
    )
    assert len(page.items) == 4
    headers = [c for c in conversation.calls if c[0] == "fetch" and c[2] == "header"]
    # The page itself, then the summaries in the inbox and in Sent.
    assert len(headers) == 3


async def test_a_thread_gone_meanwhile_leaves_the_list(
    jmap_services: Services,
    jmap_account_id: str,
    jmap_server: FakeJmap,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jmap_server.add_email(make_message("Hello"), thread="T1")
    real = JmapProvider.thread_messages

    async def gone(self: JmapProvider, thread_id: str, limit: int) -> ThreadMessages:
        if thread_id == "T1":
            raise NotFoundError("thread T1 not found")
        return await real(self, thread_id, limit)

    monkeypatch.setattr(JmapProvider, "thread_messages", gone)
    page = await jmap_services.mailbox.list_threads(
        ADMIN, jmap_account_id, folder_id="inbox", limit=10, cursor=None
    )
    assert page.items and "T1" not in [t.id for t in page.items]

    async def down(self: JmapProvider, thread_id: str, limit: int) -> ThreadMessages:
        raise ProviderUnavailableError("the server does not answer")

    monkeypatch.setattr(JmapProvider, "thread_messages", down)
    with pytest.raises(ProviderUnavailableError):
        await jmap_services.mailbox.list_threads(
            ADMIN, jmap_account_id, folder_id="inbox", limit=10, cursor=None
        )


async def test_a_folder_out_of_reach_lists_no_threads(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    with pytest.raises((ForbiddenError, NotFoundError)):
        await imap_services.mailbox.list_threads(
            reading(imap_account_id, "inbox"),
            imap_account_id,
            folder_id=SENT,
            limit=10,
            cursor=None,
        )


# --- the API -------------------------------------------------------------------------


def test_the_routes_answer_threads(
    jmap_services: Services, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    jmap_server.add_email(make_message("Hello"), thread="T1")
    jmap_server.add_email(make_message("Re: Hello"), mailbox="sent", thread="T1")
    app = create_app(Settings(storage="memory"), jmap_services)
    client = TestClient(app, headers=admin_bearer(jmap_services))
    base = f"/v1/accounts/{jmap_account_id}/threads"
    listed = client.get(base, params={"folder": "inbox"})
    assert listed.status_code == 200, listed.text
    [summary] = [t for t in listed.json()["items"] if t["id"] == "T1"]
    assert (summary["message_count"], summary["truncated"]) == (2, False)
    assert "messages" not in summary
    one = client.get(f"{base}/T1")
    assert one.status_code == 200
    assert [m["subject"] for m in one.json()["messages"]] == ["Hello", "Re: Hello"]
    assert client.get(f"{base}/T9").json()["error"]["code"] == "not_found"
    assert client.get(base).status_code == 422  # a folder is needed
    assert client.get(base, params={"folder": "inbox", "limit": 51}).status_code == 422


def test_the_own_address_stays_where_nobody_else_took_part() -> None:
    me = Address(email="Me@example.com")
    alone = MessageSummary(id="m1", **{"from": me}, to=[me])
    assert thread_of("t", "acc", [alone], own="me@example.com").participants == [me]


async def test_a_listing_threads_what_the_sync_has_not_yet(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    """As after the migration: known messages without a thread get theirs
    when they are listed, before the sync comes to them."""
    await imap_services.sync.sync_account(imap_account_id)
    index = imap_services.index
    assert isinstance(index, InMemoryMessageIndexRepository)
    own = index._entries[imap_account_id]
    for message_id, entry in own.items():
        own[message_id] = replace(entry, thread_id=None)
    index._links.clear()
    page = await imap_services.mailbox.list_threads(
        ADMIN, imap_account_id, folder_id="inbox", limit=50, cursor=None
    )
    assert len(page.items) == 4
    [mail_1] = [t for t in page.items if t.subject == "Re: Re: Mail 1"]
    assert mail_1.message_count == 2  # Re: Mail 1 in Sent is not listed yet


async def test_a_thread_shows_in_each_folder_by_its_mail_there(
    imap_services: Services, imap_account_id: str, conversation: FakeMailBox
) -> None:
    """Mail 1 and Re: Re: Mail 1 in the inbox, Re: Mail 1 in Sent: one
    thread, in both lists, each row by the newest message of its folder."""
    threads = await synced(imap_services, imap_account_id)
    mailbox = imap_services.mailbox
    [inbox] = [
        t
        for t in (
            await mailbox.list_threads(
                ADMIN, imap_account_id, folder_id="inbox", limit=50, cursor=None
            )
        ).items
        if t.id == threads["Mail 1"]
    ]
    [sent] = (
        await mailbox.list_threads(
            ADMIN, imap_account_id, folder_id=SENT, limit=50, cursor=None
        )
    ).items
    assert sent.id == inbox.id
    assert (inbox.subject, inbox.date) == (
        "Re: Re: Mail 1",
        datetime(2026, 9, 11, tzinfo=UTC),
    )
    assert (sent.subject, sent.date) == (
        "Re: Mail 1",
        datetime(2026, 9, 10, tzinfo=UTC),
    )
    assert sent.message_count == inbox.message_count == 3
    assert sent.folder_ids == inbox.folder_ids == [INBOX, SENT]
