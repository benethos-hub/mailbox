"""The outbox at the API: how a send is put in, and a job as a caller
sees it."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ....data.models import OutboxJob, OutgoingMessage


class SendRequest(OutgoingMessage):
    """A message to send, at once or through the outbox."""

    outbox: bool = Field(
        default=False,
        description=(
            "Put the message into the outbox: it is kept as a draft, the "
            "answer is `202` with the job at once, and the service sends it "
            "in the background. A provider away does not lose it."
        ),
    )
    send_at: datetime | None = Field(
        default=None,
        description=(
            "When to send it, with a time zone, at most 30 days ahead. "
            "Puts it into the outbox."
        ),
    )

    @property
    def queued(self) -> bool:
        return self.outbox or self.send_at is not None

    def message(self) -> OutgoingMessage:
        """The message alone, without how it is sent."""
        return OutgoingMessage.model_validate(
            self.model_dump(exclude={"outbox", "send_at"})
        )


class DraftSendOptions(BaseModel):
    """How a draft is sent. Without a body it is sent at once, as before."""

    outbox: bool = Field(
        default=False,
        description=(
            "Put the draft into the outbox: the answer is `202` with the "
            "job at once, the service sends it in the background."
        ),
    )
    send_at: datetime | None = Field(
        default=None,
        description=(
            "When to send it, with a time zone, at most 30 days ahead. "
            "Puts it into the outbox."
        ),
    )

    @property
    def queued(self) -> bool:
        return self.outbox or self.send_at is not None


class OutboxEntry(BaseModel):
    """A send in the outbox. Its draft waits in the drafts folder until it
    went out."""

    id: str
    account_id: str
    user_id: str = Field(description="Who queued it. It is sent with their rights.")
    operation: str = Field(description="`send_message` or `send_draft`.")
    draft_id: str = Field(description="The draft that is sent.")
    message_id_header: str = Field(description="The Message-ID it goes out with.")
    recipients: list[str]
    state: str = Field(
        description=(
            "`queued`: waits for its time. `sending`: handed to the provider "
            "now. `copying`: sent, the copy in the sent folder still "
            "missing. `sent`. `failed`: not sent, the draft stays. "
            "`unknown`: whether it went out cannot be told, it is not sent "
            "again and the draft stays. `cancelled`: not sent, the draft stays."
        )
    )
    attempts: int
    due_at: datetime = Field(description="When the next attempt is due.")
    expires_at: datetime = Field(description="After this, no further attempt.")
    send_at: datetime | None = Field(description="The time asked for, if any.")
    last_error: str | None = Field(
        description=(
            "The code of the last failure, or why it ended: such as "
            "`provider_unavailable`, `draft_changed`, `draft_gone`, "
            "`cancelled_by_user`, `no_sent_copy`."
        )
    )
    created_at: datetime
    finished_at: datetime | None = Field(description="When it was sent or ended.")

    @classmethod
    def of(cls, job: OutboxJob) -> OutboxEntry:
        return cls.model_validate(
            job.model_dump(exclude={"digest", "credential_id", "unclear_since"})
        )
