"""The token's user, its accounts and what it may do on each: ``/v1/me``."""

from __future__ import annotations

from dataclasses import dataclass


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

    user_id: str
    name: str
    accounts: list[MeAccount]
    operations: frozenset[str]
