"""The change feed: which message was created, changed or deleted, and
when. Ids only, never content (CONCEPT 6.5). Webhooks also hear of sent
mail and of accounts that need a new sign-in, as records of the same log.

``ChangeKind`` names the five kinds, ``FeedKind`` the three the change feed
answers. Their values are part of the API. The domain records each as a
class of ``domain/changes/``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedKind = Literal["message.created", "message.updated", "message.deleted"]
ChangeKind = Literal[
    "message.created",
    "message.updated",
    "message.deleted",
    "message.sent",
    "account.needs_reauth",
]
FEED_KINDS: frozenset[str] = frozenset(
    {"message.created", "message.updated", "message.deleted"}
)


class Change(BaseModel):
    """One entry in the change feed."""

    type: FeedKind = Field(
        description=(
            "`message.created`: a message arrived. `message.updated`: it "
            "moved or its flags changed. `message.deleted`: it is gone."
        )
    )
    id: str = Field(description="The message's id.")
    account_id: str
    at: datetime = Field(description="When the service noticed the change.")


class ChangeRecord(BaseModel):
    """One entry of the log behind the change feed and the webhooks.
    ``id`` is a message id, for ``message.sent`` the copy in the sent folder
    or else the Message-ID header, for ``account.needs_reauth`` the account."""

    type: ChangeKind
    id: str
    account_id: str
    at: datetime
    # The message's folder when the change was noticed, None where unknown.
    # Kept for the folders of a grant, never handed out.
    folder_id: str | None = Field(default=None, exclude=True)


class ChangePage(BaseModel):
    """Changes after a point in the feed, oldest first."""

    changes: list[Change]
    state: str = Field(
        description=("The point after these changes. Pass it as `since` next time.")
    )
    more: bool = Field(
        description="More changes wait: ask again with `state` right away."
    )
