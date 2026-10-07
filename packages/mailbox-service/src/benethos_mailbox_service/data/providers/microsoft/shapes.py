"""What Microsoft Graph sends, as shapes: mail folders, messages,
attachments, lists and errors. Every field but the id may be missing:
each call names the fields it asks for with ``$select``."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import Field, NonNegativeInt

from ...protocols import wire

T = TypeVar("T")

Text = Annotated[str | None, wire.OrNone]
Count = Annotated[NonNegativeInt | None, wire.OrNone]
Yes = Annotated[bool | None, wire.OrNone]
When = Annotated[datetime | None, wire.OrNone]


class Item(wire.CamelShape):
    """Anything Graph names by an id."""

    id: str


class Placed(wire.CamelShape):
    """Where a message is, and whether it is a draft."""

    parent_folder_id: Text = None
    is_draft: Yes = None


class MailFolder(wire.CamelShape):
    id: str
    display_name: Text = None
    parent_folder_id: Text = None
    total_item_count: Count = None
    unread_item_count: Count = None
    child_folder_count: Count = None


class EmailAddress(wire.CamelShape):
    address: Text = None
    name: Text = None


class Recipient(wire.CamelShape):
    email_address: Annotated[EmailAddress | None, wire.OrNone] = None


# A recipient of another shape is left out.
Recipients = list[Annotated[Recipient | None, wire.OrNone]]


class Flag(wire.CamelShape):
    flag_status: Text = None


class ItemBody(wire.CamelShape):
    content_type: Text = None
    content: Text = None


class Message(wire.CamelShape):
    id: str
    conversation_id: Text = None
    parent_folder_id: Text = None
    subject: Text = None
    sender: Annotated[Recipient | None, wire.OrNone] = Field(None, alias="from")
    to_recipients: Recipients = []
    cc_recipients: Recipients = []
    bcc_recipients: Recipients = []
    reply_to: Recipients = []
    received_date_time: When = None
    created_date_time: When = None
    body_preview: Text = None
    is_read: Yes = None
    flag: Annotated[Flag | None, wire.OrNone] = None
    categories: list[Annotated[str | None, wire.OrNone]] = []
    has_attachments: Yes = None
    is_draft: Yes = None
    internet_message_id: Text = None
    body: Annotated[ItemBody | None, wire.OrNone] = None
    # In a delta query: the message left the folder or is gone.
    removed: dict[str, object] | None = Field(None, alias="@removed")


class Attachment(wire.CamelShape):
    id: str
    name: Text = None
    content_type: Text = None
    size: Count = None
    is_inline: Yes = None
    content_bytes: Text = None


class Listing(wire.CamelShape, Generic[T]):
    """A page of a list, and where the next one or the delta is."""

    value: list[T] = []
    next_link: Text = Field(None, alias="@odata.nextLink")
    delta_link: Text = Field(None, alias="@odata.deltaLink")


class BatchReply(wire.CamelShape, Generic[T]):
    """One answer in a JSON batch. A body of another shape, such as an
    error, is None."""

    id: str
    status: int
    body: Annotated[T | None, wire.OrNone] = None


class Batch(wire.CamelShape, Generic[T]):
    responses: list[BatchReply[T]] = []


class ErrorDetail(wire.CamelShape):
    code: Text = None
    message: Text = None


class Failure(wire.CamelShape):
    """Graph's error body."""

    error: Annotated[ErrorDetail | None, wire.OrNone] = None
