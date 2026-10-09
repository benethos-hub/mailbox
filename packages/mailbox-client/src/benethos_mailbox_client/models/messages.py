"""Messages read: a page of summaries, the changes since a state, the
outcome of a batch, an attachment's bytes. A message and a summary stay
the JSON of the API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class Page:
    """A page of message summaries, as the API describes them."""

    items: list[dict[str, Any]]
    next_cursor: str | None
    # Accounts that did not answer, as "account: why".
    not_answering: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Change:
    """One change of the change feed: ids only."""

    type: str  # e.g. "message.created"
    id: str
    account_id: str
    at: str


@dataclass(frozen=True)
class Changes:
    """Changes after a point in the change feed, oldest first."""

    changes: list[Change]
    state: str
    more: bool


@dataclass(frozen=True)
class Failed:
    """An id a batch did not do, and why."""

    id: str
    error: str


@dataclass(frozen=True)
class Outcome:
    """A batch: the ids done, and per failed id why not."""

    done: list[str]
    failed: list[Failed]
