"""One run of ``live/changes.py``: the test accounts, the test mail, the
service and what the stages learn on the way. Finding the test mail, and
removing it at the end."""

from __future__ import annotations

import imaplib
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from benethos_mailbox_client import SyncMailboxClient

from .imap import OtherClient
from .mail import messages_with_subject
from .receiver import Receiver
from .run import Run

# How long the mail may take from SMTP to the inbox.
DELIVERY_TRIES = 10
DELIVERY_PAUSE = 3.0


def find_by_subject(
    mailbox: SyncMailboxClient, account_id: str, subject: str
) -> dict[str, Any] | None:
    found = messages_with_subject(
        mailbox, account_id, subject, tries=DELIVERY_TRIES, pause=DELIVERY_PAUSE
    )
    return found[0] if found else None


def clean_up(
    env: dict[str, str],
    receiver: dict[str, str],
    sender: dict[str, str],
    other: OtherClient | None,
    base: str,
    subject: str,
) -> None:
    """Delete the test mail wherever it is, its copy in the sender's sent
    folder, and the test folder."""
    if other is None:
        try:
            other = OtherClient(env, receiver)
        except (imaplib.IMAP4.error, OSError) as exc:
            print(f"cleanup failed, remove '{subject}' by hand: {exc}")
            return
    # A subject search finds the replies and forwards ("Re: ...") too.
    folders = [other.folder_name(base), other.folder_name(base + "-renamed")]
    places = [
        *folders,
        "INBOX",
        other.trash_folder(),
        other.sent_folder(),
        other.drafts_folder(),
    ]
    removed = sum(other.delete_mail(place, subject) for place in places if place)
    left = [f for f in folders if f in other.all_folders()]
    for folder in left:
        other.delete_folder(folder)
    other.close()
    try:
        outbox = OtherClient(env, sender)
    except (imaplib.IMAP4.error, OSError) as exc:
        print(f"cleanup failed, remove the sent copy of '{subject}' by hand: {exc}")
        return
    for place in ("INBOX", outbox.sent_folder(), outbox.trash_folder()):
        removed += outbox.delete_mail(place, subject) if place else 0
    outbox.close()
    print(
        f"\n== cleanup: {removed} test mail(s) and {len(left)} leftover "
        "folder(s) deleted"
    )


@dataclass
class Trip:
    """One run of the check: the test accounts, the test mail, the service
    and what the stages learn on the way."""

    env: dict[str, str]
    receiver: dict[str, str]
    sender: dict[str, str]
    keep: bool
    services: Any
    client: TestClient
    mailbox: SyncMailboxClient
    run: Run
    token: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    other: OtherClient | None = None
    account_id: str = ""
    sender_id: str = ""
    since: str = ""
    hooked: Receiver | None = None
    hook: dict[str, Any] = field(default_factory=dict)
    message_id: str = ""
    inbox_folder: str = ""
    sent_copy_id: str | None = None
    folder: str = ""
    test_folder: str = "?"

    @property
    def subject(self) -> str:
        return f"mailbox-service live check {self.token}"

    @property
    def base(self) -> str:
        return f"mailbox-service-live-{self.token}"

    @property
    def message_url(self) -> str:
        return f"/v1/accounts/{self.account_id}/messages/{self.message_id}"

    @property
    def folders_url(self) -> str:
        return f"/v1/accounts/{self.account_id}/folders"

    def seen_by_other(self) -> OtherClient:
        """The receiver's mailbox as another mail client sees it."""
        if self.other is None:
            self.other = OtherClient(self.env, self.receiver)
        return self.other
