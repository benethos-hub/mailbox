"""The folders of an account."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Folder:
    id: str
    name: str
    role: str | None
    unread: int | None
    total: int | None
