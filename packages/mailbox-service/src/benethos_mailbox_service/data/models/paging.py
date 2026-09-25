"""Pages of a list, and lists across accounts."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from .messages import MessageSummary

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a list. ``next_cursor`` is opaque, absent on the last page."""

    items: list[T]
    next_cursor: str | None = None


class AccountFailure(BaseModel):
    """An account that could not answer, in a list across accounts."""

    account_id: str
    code: str
    message: str


class MessagePage(Page[MessageSummary]):
    """Messages across accounts. ``incomplete`` names the accounts that did
    not answer. Their messages are missing from this page."""

    incomplete: list[AccountFailure] = Field(default_factory=list)
