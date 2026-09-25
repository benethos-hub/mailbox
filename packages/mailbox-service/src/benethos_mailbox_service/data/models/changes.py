"""The change feed: which message was created, changed or deleted, and
when. Ids only, never content (CONCEPT 6.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChangeType = Literal["message.created", "message.updated", "message.deleted"]


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


class ChangePage(BaseModel):
    """Changes after a point in the feed, oldest first."""

    changes: list[Change]
    state: str = Field(
        description=("The point after these changes. Pass it as `since` next time.")
    )
    more: bool = Field(
        description="More changes wait: ask again with `state` right away."
    )
