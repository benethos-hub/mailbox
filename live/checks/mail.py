"""Finding a test mail through the API, the change feed of a message,
and deleting test mail for good. Through the Python client."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from benethos_mailbox_client import ApiError, SyncMailboxClient

from .run import polled


def messages_with_subject(
    mailbox: SyncMailboxClient,
    account_id: str,
    subject: str,
    folder: str | None = None,
    tries: int = 10,
    pause: float = 3.0,
) -> list[dict[str, Any]]:
    """The messages with exactly ``subject`` in the account, polled through
    the API until one is there. Delivery takes a moment."""

    def look() -> list[dict[str, Any]]:
        page = mailbox.list_messages(
            account_id, subject=subject, folder=folder, limit=10
        )
        return [m for m in page.items if m.get("subject") == subject]

    return polled(look, tries, pause) or []


def feed_types(
    mailbox: SyncMailboxClient,
    account_id: str,
    since: str,
    message_id: str,
    wait: float = 0.0,
) -> list[str]:
    """The types the change feed names for one message since ``since``,
    asked until it names one or ``wait`` seconds have passed."""
    deadline = time.monotonic() + wait
    while True:
        try:
            found = mailbox.list_changes(account_id, since=since, limit=200)
        except ApiError as exc:
            return [f"status {exc.status}"]
        types = [c["type"] for c in found.changes if c["id"] == message_id]
        if types or time.monotonic() > deadline:
            return types
        time.sleep(5)


def delete_for_good(
    mailbox: SyncMailboxClient,
    places: Sequence[tuple[str, str | None]],
    subject: str,
    matches: Callable[[str], bool] | None = None,
) -> int:
    """The messages of each ``(account id, folder)``, every folder for
    None, whose subject is
    ``subject``, or for which ``matches`` holds, deleted for good. Answers
    how many."""
    fits = matches or (lambda found: found == subject)
    removed = 0
    for account_id, folder in places:
        page = mailbox.list_messages(
            account_id, folder=folder, subject=subject, limit=50
        )
        for message in page.items:
            if fits(str(message.get("subject") or "")):
                mailbox.delete_message(account_id, message["id"], permanent=True)
                removed += 1
    return removed
