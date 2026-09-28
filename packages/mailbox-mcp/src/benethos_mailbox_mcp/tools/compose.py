"""What the tools that write a message share: its addresses and the
message the tool's arguments describe."""

from __future__ import annotations

from email.utils import parseaddr
from typing import Annotated, Any, Literal

from pydantic import Field

from ..client import message_body
from ..errors import ToolError
from ..models import Recipient

Addresses = Annotated[
    list[str] | None,
    Field(max_length=100, description="Addresses, plain or as Name <address>"),
]


OriginalId = Annotated[
    str | None,
    Field(description="A message to answer or forward. Recipients and quote follow"),
]


Action = Literal["reply", "reply_all", "forward"]


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


def recipients(addresses: list[str] | None) -> list[Recipient]:
    """``Name <address>`` or plain addresses, as the model wrote them."""
    found = []
    for value in addresses or []:
        name, email = parseaddr(value)
        if "@" not in email:
            raise ToolError(f"not an address: {value}")
        found.append((email, name or None))
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
) -> dict[str, Any]:
    """The message the tool's arguments describe."""
    return message_body(
        to=recipients(to),
        cc=recipients(cc),
        bcc=recipients(bcc),
        subject=subject,
        text=text,
        html=html,
        reference=(original_id, action) if original_id is not None else None,
    )
