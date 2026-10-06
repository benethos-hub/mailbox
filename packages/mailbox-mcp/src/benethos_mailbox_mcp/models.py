"""The records the REST client answers with: small, frozen, in the terms
of the tools rather than the fields of the API.

A message, a summary in a page and a draft are not records: they stay
the JSON of the API, since ``render`` shows them whole and nothing else
reads them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# An address with an optional display name.
Recipient = tuple[str, str | None]


@dataclass(frozen=True)
class Attachment:
    """An attachment's bytes, as far as the caller's limit allowed: with
    ``complete`` False, ``data`` stops at that limit."""

    data: bytes
    content_type: str
    charset: str | None  # one Python knows, else None
    filename: str | None
    complete: bool = True


@dataclass(frozen=True)
class Sending:
    """One grant that allows sending from an account: to whom, how many in
    24 hours, how many of those are left. None: no narrowing."""

    recipients: tuple[str, ...] | None
    max_per_day: int | None
    left: int | None


@dataclass(frozen=True)
class MeAccount:
    id: str
    email: str
    display_name: str | None
    operations: frozenset[str]
    warnings: frozenset[str]
    sending: tuple[Sending, ...] = ()
    # What the account can do beyond reading its inbox, e.g. "flags",
    # "folders", "search", "drafts". None: a service that does not say.
    capabilities: frozenset[str] | None = None


@dataclass(frozen=True)
class Me:
    """The token's user: its accounts with what it may do on each, and
    what it may do beyond one account."""

    accounts: list[MeAccount]
    operations: frozenset[str]


@dataclass(frozen=True)
class Folder:
    id: str
    name: str
    role: str | None
    unread: int | None
    total: int | None


@dataclass(frozen=True)
class Page:
    """A page of message summaries, as the API describes them."""

    items: list[dict[str, Any]]
    next_cursor: str | None
    # Accounts that did not answer, as "account: why".
    not_answering: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Changes:
    """Changes after a point in the change feed, oldest first: type, id,
    account_id and at, ids only."""

    changes: list[dict[str, str]]
    state: str
    more: bool


@dataclass(frozen=True)
class Outcome:
    """A batch: the ids done, and per failed id why not."""

    done: list[str]
    failed: list[dict[str, str]]


@dataclass(frozen=True)
class Sent:
    message_id_header: str | None
    refused: list[str]
