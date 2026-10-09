"""Whether the service answers, and its version: ``/health``, open to
anyone."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Health:
    status: str
    version: str
