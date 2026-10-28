"""The folders of an account."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Folder:
    id: str
    name: str
    role: str | None
    unread: int | None
    total: int | None
    # The folder it is in, None at the top.
    parent_id: str | None = None
    # Whether it is subscribed on the server (IMAP), None where the
    # provider has no subscriptions.
    subscribed: bool | None = None
