"""Threads through the mailbox service: one with its messages, the threads
of a folder, under the grants' folders. IMAP from the index, JMAP from the
server, POP3 without."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    ForbiddenError,
    NotFoundError,
    NotSupportedError,
)

from ...conftest import ADMIN
from ...imap_fake import FakeFolder, FakeMailBox, make_message
from ...jmap_fake import FakeJmap
from ..sync.test_threads import header

SENT = mappers.folder_id("Sent")
INBOX = mappers.folder_id("INBOX")
ARCHIVE = mappers.folder_id("Archive")


def answer(subject: str, day: int, *to: str) -> bytes:
    """A reply on a day of September to the messages with these subjects."""
    return make_message(
        subject,
        date=datetime(2026, 9, day, tzinfo=UTC),
        sender="Me <me@example.com>",
        to="Alice Example <alice@example.com>",
        extra_headers={
            "In-Reply-To": header(to[-1]),
            "References": " ".join(header(s) for s in to),
        },
    )


@pytest.fixture
def conversation(imap_server: FakeMailBox) -> FakeMailBox:
    """Mail 1 in the inbox, the answer in Sent, its answer in the inbox,
    and a thread of its own in the archive."""
    imap_server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    imap_server.add("Sent", 1, answer("Re: Mail 1", 10, "Mail 1"))
    imap_server.add("INBOX", 5, answer("Re: Re: Mail 1", 11, "Mail 1", "Re: Mail 1"))
    imap_server.add("Archive", 1, make_message("Kept"))
    return imap_server


async def synced(services: Services, account_id: str) -> dict[str, str]:
    """Each subject's thread, after a sync."""
    await services.sync.sync_account(account_id)
    found: dict[str, str] = {}
    for folder in (INBOX, SENT, ARCHIVE):
        page = await services.mailbox.list_messages(
            ADMIN, account_id, folder_id=folder, limit=50, cursor=None
        )
        found.update((m.subject or "", m.thread_id or "") for m in page.items)
    return found


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
    assert [p.email for p in thread.participants] == [
        "alice@example.com",
        "me@example.com",
    ]
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
