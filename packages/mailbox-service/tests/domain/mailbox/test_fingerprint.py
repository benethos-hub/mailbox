"""What a request asked for, as a fingerprint."""

from __future__ import annotations

from benethos_mailbox_service.data.models import FolderRole, MessageFilter
from benethos_mailbox_service.domain.mailbox.fingerprint import fingerprint


def test_the_same_request_gives_the_same_fingerprint() -> None:
    one = fingerprint(FolderRole.INBOX, MessageFilter(subject="a", unread=True))
    two = fingerprint(FolderRole.INBOX, MessageFilter(unread=True, subject="a"))
    assert one == two and len(one) == 64


def test_another_request_gives_another() -> None:
    assert fingerprint("send", None) != fingerprint("reply", None)
    assert fingerprint(FolderRole.INBOX, None) != fingerprint(FolderRole.SENT, None)
