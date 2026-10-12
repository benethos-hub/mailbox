"""Threads: the messages of one account that answer each other, in every
folder (CONCEPT 6.3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .messages import Address, MessageSummary


class ThreadSummary(BaseModel):
    """A thread as a list shows it, from the messages the caller may see."""

    id: str
    account_id: str
    subject: str | None = Field(default=None, description="Of the newest message.")
    participants: list[Address] = Field(
        default_factory=list,
        description="Who wrote and who was written to, each once, in the "
        "order they first appear. The account's own address only where "
        "nobody else took part.",
    )
    message_count: int = Field(description="The messages listed.")
    unread_count: int
    date: datetime | None = Field(default=None, description="Of the newest message.")
    snippet: str | None = Field(default=None, description="Of the newest message.")
    folder_ids: list[str] = Field(
        default_factory=list, description="The folders of its messages, each once."
    )
    truncated: bool = Field(
        default=False,
        description="The thread holds more messages than are listed: only the "
        "newest are, as many as `MAILBOX_SERVICE_THREAD_MESSAGES` allows.",
    )


class Thread(ThreadSummary):
    """A thread with its messages, oldest first."""

    messages: list[MessageSummary]
