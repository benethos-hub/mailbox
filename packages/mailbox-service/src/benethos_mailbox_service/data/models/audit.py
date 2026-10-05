"""The audits: of sends, who sent from which account to whom, never
content. Of administration, who signed in and who changed what."""

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


ActivityOutcome = Literal["done", "refused", "failed"]


class ActivityRecord(BaseModel):
    """One activity of administration someone caused (docs/AUDIT.md). It
    keeps no reference to a user or an account, so it outlives both."""

    id: str
    at: datetime
    activity: str = Field(
        description=(
            "What happened, as the service log names it: `users.token_revoked`, "
            "`auth.sign_in_failed`."
        )
    )
    user_id: str | None = Field(
        description="Who acted. Null for a caller not signed in and for the host."
    )
    user_name: str = Field(
        description=(
            "The name as it was then. `someone` for a caller not signed in, "
            "`the host` for a command on the host."
        )
    )
    credential: str | None = Field(
        description=(
            "How the caller came: `token:<id>`, `password` for the UI, `host` "
            "for a command on the host, null without one."
        )
    )
    record: str | None = Field(
        description=(
            "The id of what was touched: a user, token, role, account or webhook."
        )
    )
    source: str | None = Field(description="The client address, null without one.")
    outcome: ActivityOutcome = Field(
        description=(
            "`done`. `refused`: a sign-in, a token or a request the service "
            "turned away. `failed`: an error."
        )
    )
    detail: str = Field(
        description=(
            "What was done and why, as the log line says it. Never a secret, "
            "never mail content."
        )
    )


class ActivityFilter(BaseModel):
    """What narrows the audit of administration. Each field set must match."""

    user_id: str | None = None
    # A name such as users.token_revoked, or an area such as users.
    activity: str | None = None
    record: str | None = None
    # Activities at or after this time, and before that one.
    after: datetime | None = None
    before: datetime | None = None

    def matches(self, record: ActivityRecord) -> bool:
        return (
            (self.user_id is None or record.user_id == self.user_id)
            and (self.activity is None or of_activity(record.activity, self.activity))
            and (self.record is None or record.record == self.record)
            and (self.after is None or record.at >= self.after)
            and (self.before is None or record.at < self.before)
        )


def of_activity(name: str, wanted: str) -> bool:
    """Whether an activity's name is ``wanted`` or lies in that area."""
    return name == wanted or name.startswith(f"{wanted}.")
