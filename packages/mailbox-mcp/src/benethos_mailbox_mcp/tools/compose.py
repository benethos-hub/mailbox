"""What the tools that write a message share: its addresses, its
attachments and the message the tool's arguments describe."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from benethos_mailbox_common.mail import addresses as typed_addresses

from ..client import message_body
from ..errors import ToolError
from ..models import AttachmentSource, OutgoingFile, Recipient, Reference

Addresses = Annotated[
    list[str] | None,
    Field(max_length=100, description="Addresses, plain or as Name <address>"),
]


ReplyTo = Annotated[
    list[str] | None,
    Field(
        max_length=10,
        description="Where answers should go instead of this account's address",
    ),
]


OriginalId = Annotated[
    str | None,
    Field(description="A message to answer or forward. Recipients and quote follow"),
]


Action = Literal["reply", "reply_all", "forward"]


Quote = Annotated[
    bool,
    Field(
        description=(
            "With original_id: false adds nothing of the original, no quote of a"
            " reply and no forwarded message. The link to it stays"
        )
    ),
]


ForwardAs = Annotated[
    Literal["inline", "attachment"],
    Field(
        description=(
            "A forward: inline quotes the original below the text with its"
            " attachments, attachment attaches it unchanged as a file"
        )
    ),
]


Text = Annotated[str, Field(description="The body as plain text")]


Html = Annotated[
    str | None,
    Field(
        description=(
            "The body as HTML, for formatting. Inline styles only (style=...),"
            " since many mail programs drop <style> blocks. Without text, the text"
            " part is made from it"
        )
    ),
]


class NewFile(BaseModel):
    """A file to attach that the caller made, such as an invitation."""

    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(
        default="application/octet-stream",
        description="Its type, e.g. text/calendar, text/csv, application/pdf",
    )
    data: str = Field(description="The content, base64-encoded")


class FromMessage(BaseModel):
    """An attachment of another mail of the same account."""

    message_id: str
    attachment_id: str = Field(description="As get_message lists it")


Attachments = Annotated[
    list[NewFile] | None,
    Field(max_length=20, description="Files to attach, 25 MiB together at most"),
]


AttachFrom = Annotated[
    list[FromMessage] | None,
    Field(
        max_length=20,
        description=(
            "Attachments of other mail of this account, attached as they are,"
            " before attachments. Needs the right to read that mail"
        ),
    ),
]


def recipients(addresses: list[str] | None) -> list[Recipient]:
    """``Name <address>`` or plain addresses, as the model wrote them,
    one in each."""
    found = []
    for value in addresses or []:
        typed = typed_addresses.parsed(value)
        if len(typed) != 1 or "@" not in typed[0].email:
            raise ToolError(f"not an address: {value}")
        found.append((typed[0].email, typed[0].name))
    return found


def files(attachments: list[NewFile] | None) -> list[OutgoingFile]:
    """The files the model gave, decoded."""
    found = []
    for attachment in attachments or []:
        try:
            data = base64.b64decode(attachment.data, validate=True)
        except binascii.Error:
            raise ToolError(f"not base64: the data of {attachment.filename}") from None
        found.append(OutgoingFile(attachment.filename, data, attachment.content_type))
    return found


def composed(
    to: list[str] | None,
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    text: str,
    html: str | None,
    original_id: str | None,
    action: Action,
    *,
    reply_to: list[str] | None = None,
    quote: bool = True,
    forward_as: Literal["inline", "attachment"] = "inline",
    attachments: list[NewFile] | None = None,
    attach_from: list[FromMessage] | None = None,
) -> dict[str, Any]:
    """The message the tool's arguments describe."""
    return message_body(
        to=recipients(to),
        cc=recipients(cc),
        bcc=recipients(bcc),
        subject=subject,
        text=text,
        html=html,
        reference=(
            Reference(original_id, action, forward_as=forward_as, quote=quote)
            if original_id is not None
            else None
        ),
        reply_to=recipients(reply_to),
        attachments=files(attachments),
        attachments_from=[
            AttachmentSource(source.message_id, source.attachment_id)
            for source in attach_from or []
        ],
    )
