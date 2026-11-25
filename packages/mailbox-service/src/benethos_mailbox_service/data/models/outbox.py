"""The outbox: a send waiting in the account's drafts folder until the
service hands it to the provider. A job holds where the draft is and
what it was when queued, never its content."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OutboxState = Literal[
    "queued", "sending", "copying", "sent", "failed", "unknown", "cancelled"
]

# The states the runner still works on. Every other one is final.
OPEN_STATES: tuple[OutboxState, ...] = ("queued", "sending", "copying")


class OutboxJob(BaseModel):
    """One send in the outbox."""

    id: str
    account_id: str
    user_id: str = Field(description="Who queued it. The send runs with their rights.")
    credential_id: str | None = Field(
        description="The token used to queue it, null from the UI."
    )
    operation: Literal["send_message", "send_draft"]
    draft_id: str = Field(description="The draft in the drafts folder that is sent.")
    digest: str = Field(
        description="SHA-256 of the draft as stored when queued, to notice a change."
    )
    message_id_header: str = Field(
        description="The Message-ID every attempt sends, so a sent copy is found."
    )
    recipients: list[str]
    state: OutboxState = Field(
        description=(
            "`queued`: waits for its time. `sending`: handed to the provider "
            "now. `copying`: sent, the copy in the sent folder still missing. "
            "`sent`. `failed`: not sent, the draft stays. `unknown`: whether "
            "it went out cannot be told, it is not tried again. `cancelled`: "
            "not sent, the draft stays."
        )
    )
    attempts: int = 0
    due_at: datetime = Field(description="When the next attempt is due.")
    expires_at: datetime = Field(description="After this, no further attempt.")
    send_at: datetime | None = Field(
        default=None, description="The time asked for, null for at once."
    )
    last_error: str | None = Field(
        default=None, description="The error code of the last attempt, if any."
    )
    unclear_since: datetime | None = Field(
        default=None,
        description="Since when an attempt with an unclear outcome is looked into.",
    )
    created_at: datetime
    finished_at: datetime | None = None

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES
