"""The mail objects of JMAP (RFC 8621) as shapes. Every field but the id
may be missing: each call names the properties it asks for."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, NonNegativeInt

from ...protocols import wire

Text = Annotated[str | None, wire.OrNone]
Count = Annotated[NonNegativeInt | None, wire.OrNone]


class Mailbox(wire.CamelShape):
    """A mailbox, a folder of the API (RFC 8621 2)."""

    id: str
    name: Text = None
    parent_id: Text = None
    role: Text = None
    total_emails: Count = None
    unread_emails: Count = None
    is_subscribed: Annotated[bool | None, wire.OrNone] = None


class EmailAddress(wire.CamelShape):
    email: Text = None
    name: Text = None


# An address of another shape is left out.
Addresses = list[Annotated[EmailAddress | None, wire.OrNone]]
When = Annotated[datetime | None, wire.OrNone]


class Email(wire.CamelShape):
    """An email (RFC 8621 4)."""

    id: str
    blob_id: Text = None
    thread_id: Text = None
    mailbox_ids: dict[str, bool] = {}
    keywords: dict[str, bool] = {}
    received_at: When = None
    sent_at: When = None
    subject: Text = None
    sender: Addresses = Field(default=[], alias="from")
    to: Addresses = []
    preview: Text = None
    has_attachment: Annotated[bool | None, wire.OrNone] = None
    message_id: Annotated[list[str] | None, wire.OrNone] = None


class Identity(wire.CamelShape):
    """An identity to send as (RFC 8621 6)."""

    id: str
    email: Text = None
