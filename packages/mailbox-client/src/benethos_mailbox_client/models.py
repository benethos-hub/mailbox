"""The records the client answers with: small, frozen, in the terms of
a caller rather than the fields of the API.

A message, a summary in a page and a draft are not records: they stay
the JSON of the API, which describes them in docs/openapi.json."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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


class Secret:
    """A secret the service shows once, e.g. a webhook's signing secret:
    kept out of ``repr`` and ``str`` so it reaches no log by accident, read
    with ``get_secret_value()``."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('**********')"

    def __str__(self) -> str:
        return "**********"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class Webhook:
    """A URL that hears of events. ``accounts`` None: every account its
    owner may read, accounts added later included."""

    id: str
    url: str
    events: tuple[str, ...]
    accounts: tuple[str, ...] | None
    user_id: str
    created_at: datetime
    last_delivery_at: datetime | None
    # Why the last post failed, if it did.
    last_error: str | None


@dataclass(frozen=True)
class WebhookSecret:
    """A webhook's new signing secret, shown this once. The one before
    stops at once."""

    webhook_id: str
    secret: Secret
