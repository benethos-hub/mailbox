"""Limits the service enforces (docs/LOGGING.md 5.9). Each is logged once
when it engages, not for every request it refuses: that request answers
``429`` with ``Retry-After``, and the access log has its line.

Pauses a provider asks for are the lines of an account that cannot be
reached (``accounts``), with the provider's reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import User
from ..base import Activity, user


@dataclass(frozen=True, kw_only=True)
class SourceLockedOut(Activity):
    """Too many failed sign-ins from one client address. ``by`` is that
    address."""

    level: ClassVar[int] = logging.WARNING

    minutes: int

    def says(self) -> str:
        return "failed to sign in too often"

    def why(self) -> str:
        return f"locked out for {self.minutes} minutes"


@dataclass(frozen=True, kw_only=True)
class LockoutEnded(Activity):
    """Noticed at the next attempt after the lockout ran out."""

    def says(self) -> str:
        return "may try to sign in again"

    def why(self) -> str:
        return "the lockout ended"


@dataclass(frozen=True, kw_only=True)
class NameBraked(Activity):
    """Too many failed sign-ins as one user name, from any address. The
    user when the name is a user's, else nobody: the name as typed may be
    a password."""

    level: ClassVar[int] = logging.WARNING

    user: User | None
    seconds: int

    def says(self) -> str:
        who = user(self.user) if self.user is not None else "an unknown name"
        return f"failed to sign in as {who} too often"

    def why(self) -> str:
        return f"the name waits {self.seconds} seconds"


@dataclass(frozen=True, kw_only=True)
class DiscoveryLimitReached(Activity):
    level: ClassVar[int] = logging.WARNING

    limit: int

    def says(self) -> str:
        return f"reached the discovery limit of {self.limit} in a minute"


@dataclass(frozen=True, kw_only=True)
class SendLimitReached(Activity):
    """The grants' limit of mails in 24 hours. The audit of sends has the
    attempt as ``denied``."""

    level: ClassVar[int] = logging.WARNING

    account_id: str
    reason: str
    retry_after: int

    def says(self) -> str:
        return f"reached the send limit on {self.account_id}"

    def why(self) -> str:
        return f"{self.reason}, the next in {self.retry_after}s"


@dataclass(frozen=True, kw_only=True)
class BodyTooLarge(Activity):
    """Refused by the web layer before the domain saw the request."""

    level: ClassVar[int] = logging.WARNING

    path: str
    limit: int

    def says(self) -> str:
        megabytes = self.limit // (1024 * 1024)
        return f"sent a request to {self.path} larger than {megabytes} MB"

    def why(self) -> str:
        return "refused"
