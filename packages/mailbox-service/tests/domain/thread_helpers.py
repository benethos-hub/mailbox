"""Threads of an IMAP account in tests: replies, the threads after a
sync, the threads of a folder page by page."""

from __future__ import annotations

from datetime import UTC, datetime

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.providers.imap import mappers

from ..conftest import ADMIN
from ..imap_fake import make_message
from .sync_helpers import header

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


async def every_thread(
    services: Services, account_id: str, folder: str, limit: int
) -> list[str]:
    """The ids of the threads of a folder, page by page."""
    shown: list[str] = []
    cursor = None
    while True:
        page = await services.mailbox.list_threads(
            ADMIN, account_id, folder_id=folder, limit=limit, cursor=cursor
        )
        shown += [t.id for t in page.items]
        cursor = page.next_cursor
        if cursor is None:
            return shown
