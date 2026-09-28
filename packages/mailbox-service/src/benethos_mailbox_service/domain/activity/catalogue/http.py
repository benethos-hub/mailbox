"""What the web layer refuses before the domain sees a request
(docs/LOGGING.md 5.9, rule 6.2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ..base import Activity


@dataclass(frozen=True, kw_only=True)
class BodyTooLarge(Activity):
    """Refused by the web layer before the domain saw the request."""

    name: ClassVar[str] = "body_too_large"
    level: ClassVar[int] = logging.WARNING

    path: str
    limit: int

    def says(self) -> str:
        megabytes = self.limit // (1024 * 1024)
        return f"sent a request to {self.path} larger than {megabytes} MB"

    def why(self) -> str:
        return "refused"
