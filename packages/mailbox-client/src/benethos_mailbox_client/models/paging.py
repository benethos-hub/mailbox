"""A page of records and the cursor of the next one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class Paged(Generic[R]):
    """A page of records: accounts, users, sends, the audit. With
    ``next_cursor`` the list goes on, asked with that cursor."""

    items: list[R]
    next_cursor: str | None
