"""The audit of sends: each attempt to send, and how it came out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SendRecord:
    """One attempt to send from an account. ``operation`` is
    ``send_message`` or ``send_draft``, ``outcome`` ``sent``, ``denied`` or
    ``failed`` with its ``error``, ``refused`` the recipients the server
    did not take."""

    id: str
    created_at: datetime
    user_id: str
    credential_id: str | None
    account_id: str
    operation: str
    recipients: tuple[str, ...]
    outcome: str
    error: str | None
    refused: tuple[str, ...]
    message_id_header: str | None
