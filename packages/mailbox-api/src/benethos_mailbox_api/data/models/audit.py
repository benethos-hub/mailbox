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
        description="The token used; null for the admin key."
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
