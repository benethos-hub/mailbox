"""Autodiscovery (docs/LOGGING.md 5.8, 5.9). A lookup names the domain
alone: the local part of the address is the person's."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....common.text import plural
from ..base import Activity


@dataclass(frozen=True, kw_only=True)
class Discovered(Activity):
    """The domain alone: the local part of the address is the person's."""

    name: ClassVar[str] = "looked_up"
    level: ClassVar[int] = logging.DEBUG

    domain: str
    candidates: int
    sources: int

    def says(self) -> str:
        return (
            f"looked up the servers of {self.domain}: "
            f"{plural(self.candidates, 'candidate')} from "
            f"{plural(self.sources, 'source')}"
        )


@dataclass(frozen=True, kw_only=True)
class DiscoveryLimitReached(Activity):
    name: ClassVar[str] = "limit_reached"
    level: ClassVar[int] = logging.WARNING

    limit: int

    def says(self) -> str:
        return f"reached the discovery limit of {self.limit} in a minute"
