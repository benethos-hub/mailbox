"""The change feed: which message was created, changed or deleted, and
when. Ids only, never content (CONCEPT 6.5). Webhooks also hear of sent
mail and of accounts that need a new sign-in, as events of the same log."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChangeType = Literal["message.created", "message.updated", "message.deleted"]
EventType = Literal[
    "message.created",
    "message.updated",
    "message.deleted",
    "message.sent",
    "account.needs_reauth",
]
CHANGE_TYPES: frozenset[str] = frozenset(
    {"message.created", "message.updated", "message.deleted"}
)


class Change(BaseModel):
    """One entry in the change feed."""

    type: ChangeType = Field(
        description=(
            "`message.created`: a message arrived. `message.updated`: it "
            "moved or its flags changed. `message.deleted`: it is gone."
        )
    )
    id: str = Field(description="The message's id.")
    account_id: str
    at: datetime = Field(description="When the service noticed the change.")


class Event(BaseModel):
    """One entry of the log behind the change feed and the webhooks.
    ``id`` is a message id, for ``message.sent`` the copy in the sent folder
    or else the Message-ID header, for ``account.needs_reauth`` the account."""

    type: EventType
    id: str
    account_id: str
    at: datetime


class ChangePage(BaseModel):
    """Changes after a point in the feed, oldest first."""

    changes: list[Change]
    state: str = Field(
        description=("The point after these changes. Pass it as `since` next time.")
    )
    more: bool = Field(
        description="More changes wait: ask again with `state` right away."
    )
