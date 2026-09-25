"""Outgoing messages: what a caller sends, and what comes back."""

from __future__ import annotations

from pydantic import Base64Bytes, BaseModel, Field

from .messages import MessageReference, MessageSummary

# No line break in anything that goes into a header: a CR or LF there would
# let a caller add headers of its own (header injection). The other
# characters are what ``str.splitlines`` breaks on as well, and the standard
# library refuses a header value with any of them.
_ONE_LINE = r"^[^\r\n\x0b\x0c\x1c-\x1e\x85\u2028\u2029]*$"


class Recipient(BaseModel):
    email: str = Field(pattern=r"^[^\s@<>,;\"]+@[^\s@<>,;\"]+$", max_length=254)
    name: str | None = Field(default=None, pattern=_ONE_LINE, max_length=200)


class OutgoingAttachment(BaseModel):
    filename: str = Field(pattern=_ONE_LINE, min_length=1, max_length=200)
    content_type: str = Field(
        default="application/octet-stream",
        pattern=r"^[\w.+-]+/[\w.+-]+$",
    )
    data: Base64Bytes = Field(description="The content, base64-encoded.")


class DraftMessage(BaseModel):
    """A draft: a message that may still lack recipients. The service sets
    From, Date and Message-ID."""

    reference: MessageReference | None = None
    to: list[Recipient] = Field(default_factory=list)
    cc: list[Recipient] = Field(default_factory=list)
    bcc: list[Recipient] = Field(
        default_factory=list, description="Receive it, but appear in no header."
    )
    reply_to: list[Recipient] = Field(default_factory=list)
    subject: str = Field(default="", pattern=_ONE_LINE, max_length=998)
    text: str | None = Field(
        default=None,
        description="Plain text. Left out beside `html`: made from the HTML.",
    )
    html: str | None = Field(
        default=None,
        description="HTML, sent beside a text part (multipart/alternative).",
    )
    attachments: list[OutgoingAttachment] = Field(default_factory=list)

    def recipients(self) -> list[str]:
        """Every address the message goes to, each once."""
        return list(dict.fromkeys(r.email for r in (*self.to, *self.cc, *self.bcc)))


class OutgoingMessage(DraftMessage):
    """A message to send. The service sets From, Date and Message-ID. It
    needs a recipient, unless it is a reply: that finds one in the original."""


class SendResult(BaseModel):
    message_id_header: str = Field(description="The Message-ID of the sent message.")
    sent_copy_id: str | None = Field(
        default=None,
        description="The copy in the sent folder, where the service put one.",
    )
    refused: list[str] = Field(
        default_factory=list,
        description="Recipients the server refused while it accepted others.",
    )


class SentMessage(BaseModel):
    """What a provider reports about a send."""

    refused: list[str] = Field(default_factory=list)
    sent_copy: MessageSummary | None = None
