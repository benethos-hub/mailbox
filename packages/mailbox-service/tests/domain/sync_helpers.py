"""The sync from outside: its worker, the ids it gave, what it recorded."""

from __future__ import annotations

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.domain.sync.worker import SyncWorker

from ..conftest import ADMIN


def recorded(services: Services, account_id: str) -> list[tuple[str, str, str | None]]:
    return [
        (e.record.type, e.record.id, e.record.folder_id)
        for e in services.changes.after([account_id], 0, limit=1000)
    ]


async def ids_by_subject(
    imap_services: Services, imap_account_id: str
) -> dict[str, str]:
    page = await imap_services.mailbox.list_messages(
        ADMIN,
        imap_account_id,
        folder_id=None,
        limit=50,
        cursor=None,
    )
    return {m.subject or "": m.id for m in page.items}


def header(subject: str) -> str:
    return f"<{abs(hash(subject))}@example.com>"


def worker(imap_services: Services, **options: object) -> SyncWorker:
    async def no_sleep(seconds: float) -> None:
        return None

    return SyncWorker(
        imap_services.adapters,
        imap_services.sync,
        interval=300,
        sleep=no_sleep,
        **options,  # type: ignore[arg-type]
    )
