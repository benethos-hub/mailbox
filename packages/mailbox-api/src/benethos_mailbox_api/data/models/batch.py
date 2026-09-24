"""One action for many messages, and a result per message."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .messages import MessageSummary, MessageUpdate


class MessageBatch(BaseModel):
    """One action for up to 100 messages of one account."""

    ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["update", "delete"]
    changes: MessageUpdate | None = Field(
        default=None, description="For `update`: what changes, as in `PATCH`."
    )
    permanent: bool = Field(
        default=False,
        description="For `delete`: for good instead of into the trash.",
    )

    @model_validator(mode="after")
    def _changes_for_update(self) -> MessageBatch:
        if self.action == "update" and self.changes is None:
            raise ValueError("an update needs changes")
        self.ids = list(dict.fromkeys(self.ids))
        return self


class ItemError(BaseModel):
    code: str
    message: str


class BatchItemResult(BaseModel):
    id: str
    ok: bool
    message: MessageSummary | None = Field(
        default=None, description="After an update, the message as it is now."
    )
    error: ItemError | None = None


class BatchResult(BaseModel):
    """One result per id, in the order of the request."""

    results: list[BatchItemResult]
