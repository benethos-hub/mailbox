"""What the web layer refuses before the domain sees a request, or
before a route does its work (docs/LOGGING.md 5.9, rule 6.2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....common.sizes import megabytes
from ....data.models import ActivityOutcome
from ..base import Activity


@dataclass(frozen=True, kw_only=True)
class BodyTooLarge(Activity):
    """Refused by the web layer before the domain saw the request."""

    name: ClassVar[str] = "body_too_large"
    level: ClassVar[int] = logging.WARNING

    path: str
    limit: int

    def says(self) -> str:
        return f"sent a request to {self.path} larger than {megabytes(self.limit)}"

    def why(self) -> str:
        return "refused"


@dataclass(frozen=True, kw_only=True)
class RequestsLimited(Activity):
    """A token, a UI session or a client address ran out of requests.
    Written once when the limit engages, not per refused request."""

    name: ClassVar[str] = "rate_limited"
    audited: ClassVar[bool] = True
    outcome: ClassVar[ActivityOutcome] = "refused"
    level: ClassVar[int] = logging.WARNING

    path: str
    per_minute: int
    seconds: int

    def says(self) -> str:
        return f"sent too many requests, the last to {self.path}"

    def why(self) -> str:
        unit = "second" if self.seconds == 1 else "seconds"
        return (
            f"limited to {self.per_minute} a minute, refused for {self.seconds} {unit}"
        )
