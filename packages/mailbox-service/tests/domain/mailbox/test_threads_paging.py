"""The threads of an IMAP folder page by page where the folder does not
list by date: a mail filed late, ties in one second over several pages,
and a message the index has no thread for yet."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.storage import (
    IndexEntry,
    InMemoryMessageIndexRepository,
)
from benethos_mailbox_service.errors import NotFoundError

from ...conftest import ADMIN
from ...imap_fake import FakeFolder, FakeMailBox, make_message
from ..sync_helpers import header
from ..thread_helpers import answer, every_thread, synced


@pytest.fixture
def late_filed(imap_server: FakeMailBox) -> FakeMailBox:
    """Mail 1 (Sep 1) and its answer (Sep 11) in the inbox, then a mail of
    August moved into the inbox, the highest UID with the oldest date,
    and two newer ones."""
    imap_server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    imap_server.add("INBOX", 5, answer("Re: Mail 1", 11, "Mail 1"))
    imap_server.add(
        "INBOX", 6, make_message("Old", date=datetime(2026, 8, 1, tzinfo=UTC))
    )
    for uid, day in ((7, 20), (8, 21)):
        imap_server.add(
            "INBOX",
            uid,
            make_message(f"New {day}", date=datetime(2026, 9, day, tzinfo=UTC)),
        )
    return imap_server


@pytest.mark.parametrize("folder", ["inbox", "all"])
@pytest.mark.parametrize("limit", [1, 2, 3, 6])
async def test_a_mail_filed_late_hides_no_thread(
    imap_services: Services,
    imap_account_id: str,
    late_filed: FakeMailBox,
    folder: str,
    limit: int,
) -> None:
    """With limit 2 the old mail opens the second page, beside the answer
    to Mail 1, whose thread must show there."""
    await synced(imap_services, imap_account_id)
    whole = await every_thread(imap_services, imap_account_id, folder, 50)
    shown = await every_thread(imap_services, imap_account_id, folder, limit)
    assert len(shown) == len(set(shown))
    assert set(shown) == set(whole)


@pytest.fixture
def tied(imap_server: FakeMailBox) -> FakeMailBox:
    """A thread of three messages and another message, all in one
    second, in the inbox."""
    when = datetime(2026, 9, 20, 12, tzinfo=UTC)

    def reply(subject: str, to: str) -> bytes:
        return make_message(
            subject, date=when, extra_headers={"In-Reply-To": header(to)}
        )

    imap_server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    imap_server.add("INBOX", 10, make_message("Tie", date=when))
    imap_server.add("INBOX", 11, reply("Re: Tie", "Tie"))
    imap_server.add("INBOX", 12, make_message("Other", date=when))
    imap_server.add("INBOX", 13, reply("Re: Re: Tie", "Re: Tie"))
    return imap_server


@pytest.mark.parametrize("limit", [1, 2, 3])
async def test_ties_in_one_second_over_three_pages_show_once(
    imap_services: Services, imap_account_id: str, tied: FakeMailBox, limit: int
) -> None:
    await synced(imap_services, imap_account_id)
    shown = await every_thread(imap_services, imap_account_id, "inbox", limit)
    whole = await every_thread(imap_services, imap_account_id, "inbox", 50)
    assert len(shown) == len(set(shown))
    assert set(shown) == set(whole)


def entries(services: Services, account_id: str) -> dict[str, IndexEntry]:
    index = services.index
    assert isinstance(index, InMemoryMessageIndexRepository)
    return index._entries[account_id]


async def test_a_message_without_a_thread_is_a_thread_of_its_own(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listed under its own id, which finds the message alone and, once
    it has a thread, that thread."""
    imap_server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    threads = await synced(imap_services, imap_account_id)
    mailbox = imap_services.mailbox
    page = await mailbox.list_messages(
        ADMIN, imap_account_id, folder_id="inbox", limit=50, cursor=None
    )
    [mail_2] = [m for m in page.items if m.subject == "Mail 2"]
    # As when its headers could not be read: no thread in the index.
    own = entries(imap_services, imap_account_id)
    threaded = own[mail_2.id]
    own[mail_2.id] = replace(threaded, thread_id=None)

    async def no_headers(natives: list[str]) -> dict[str, object]:
        return {}

    monkeypatch.setattr(
        imap_services.sync, "_headers", lambda account_id, natives: no_headers(natives)
    )
    listed = await mailbox.list_threads(
        ADMIN, imap_account_id, folder_id="inbox", limit=50, cursor=None
    )
    [alone] = [t for t in listed.items if t.subject == "Mail 2"]
    assert alone.id == mail_2.id
    assert alone.message_count == 1
    assert len(listed.items) == 4
    thread = await mailbox.get_thread(ADMIN, imap_account_id, mail_2.id)
    assert (thread.id, [m.id for m in thread.messages]) == (mail_2.id, [mail_2.id])
    # Threaded meanwhile: the id finds the thread it is in now.
    monkeypatch.undo()
    own[mail_2.id] = threaded
    later = await mailbox.get_thread(ADMIN, imap_account_id, mail_2.id)
    assert later.id == threads["Mail 2"]


async def test_an_id_of_no_message_finds_no_thread(
    imap_services: Services, imap_account_id: str
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    with pytest.raises(NotFoundError, match="thread msg_none"):
        await imap_services.mailbox.get_thread(ADMIN, imap_account_id, "msg_none")
