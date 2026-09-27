"""The audit of sends: who sent from which account to whom, never content."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SendOutcome = Literal["sent", "denied", "failed"]


class SendRecord(BaseModel):
    """One attempt to send: a mail or a draft."""

    id: str
    created_at: datetime
    user_id: str
    credential_id: str | None = Field(
        description="The token used, null for a send from the UI."
    )
    account_id: str
    operation: Literal["send_message", "send_draft"]
    recipients: list[str]
    outcome: SendOutcome = Field(
        description=(
            "`sent`: the mail server took it. `denied`: a grant's recipients "
            "or send limit stopped it. `failed`: an error before or while "
            "sending."
        )
    )
    error: str | None = Field(default=None, description="The error code, if any.")
    refused: list[str] = Field(
        default_factory=list,
        description="Recipients the server refused while it accepted others.",
    )
    message_id_header: str | None = None


class SendFilter(BaseModel):
    """What narrows the audit of sends. Each field set must match."""

    user_id: str | None = None
    outcome: SendOutcome | None = None
    # A part of a recipient's address, regardless of case.
    recipient: str | None = None
    # Sends at or after this time, and before that one.
    after: datetime | None = None
    before: datetime | None = None

    def matches(self, record: SendRecord) -> bool:
        wanted = (self.recipient or "").casefold()
        return (
            (self.user_id is None or record.user_id == self.user_id)
            and (self.outcome is None or record.outcome == self.outcome)
            and (not wanted or any(wanted in r.casefold() for r in record.recipients))
            and (self.after is None or record.created_at >= self.after)
            and (self.before is None or record.created_at < self.before)
        )
