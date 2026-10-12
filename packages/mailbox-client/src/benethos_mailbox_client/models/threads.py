"""Threads: the messages of one account that answer each other, in every
folder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .messages import Address, MessageSummary


@dataclass(frozen=True, slots=True)
class ThreadSummary:
    """A thread in a list, from the messages the caller may see. Subject,
    date and snippet are those of its newest message. ``truncated``: the
    thread holds more messages than the service lists."""

    id: str
    account_id: str
    subject: str | None
    participants: list[Address]
    message_count: int
    unread_count: int
    date: datetime | None
    snippet: str | None
    folder_ids: list[str]
    truncated: bool


@dataclass(frozen=True, slots=True)
class Thread(ThreadSummary):
    """A thread with its messages, oldest first."""

    messages: list[MessageSummary]
