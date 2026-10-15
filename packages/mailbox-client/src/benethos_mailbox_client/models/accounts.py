"""Connected mailboxes as the API describes them, never a secret."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class StoredCredential:
    """That a credential of an account is stored, e.g. ``password``, and
    since when. Never its value."""

    field: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Marks:
    """The marks of RFC 8621 an account reads and those it writes, such
    as ``$answered``. Writing one it does not write fails with 501."""

    read: frozenset[str] = frozenset()
    written: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Account:
    """A connected mailbox. ``provider`` is the kind, e.g. ``imap``,
    ``status`` e.g. ``connected`` or ``needs_reauth``. ``settings`` are
    the connection settings, never a secret."""

    id: str
    provider: str
    email: str
    display_name: str | None
    status: str
    credentials: tuple[StoredCredential, ...]
    settings: dict[str, Any]
    # What the account can do beyond reading its inbox, e.g. "read_state",
    # "move", "search", "drafts". Empty until its server was asked once.
    capabilities: frozenset[str]
    marks: Marks = Marks()
