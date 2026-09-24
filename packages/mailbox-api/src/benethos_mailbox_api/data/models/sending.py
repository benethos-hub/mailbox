"""Outgoing messages: what a caller sends, and what comes back."""

from __future__ import annotations

from typing import Literal

from pydantic import Base64Bytes, BaseModel, Field, model_validator

from .messages import MessageSummary

# No line breaks in anything that goes into a header: a CR or LF there would
# let a caller add headers of its own (header injection).
_ONE_LINE = r"^[^\r\n]*$"
MAX_RECIPIENTS = 100
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


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


class MessageReference(BaseModel):
    """Reply to or forward a message of the same account. The service sets
    the recipients of a reply where none are given, the subject prefix,
    In-Reply-To, References and the quote."""

    message_id: str
    action: Literal["reply", "reply_all", "forward"]
    forward_as: Literal["inline", "attachment"] = Field(
        default="inline",
        description=(
            "`inline`: quoted with its headers, its attachments attached. "
            "`attachment`: the unchanged original as `message/rfc822`. "
            "Ignored for replies."
        ),
    )


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

    @model_validator(mode="after")
    def _limits(self) -> DraftMessage:
        if len(self.recipients()) > MAX_RECIPIENTS:
            raise ValueError(f"at most {MAX_RECIPIENTS} recipients")
        if sum(len(a.data) for a in self.attachments) > MAX_ATTACHMENT_BYTES:
            raise ValueError("the attachments exceed 25 MB")
        return self

    def recipients(self) -> list[str]:
        """Every address the message goes to, each once."""
        return list(dict.fromkeys(r.email for r in (*self.to, *self.cc, *self.bcc)))


class OutgoingMessage(DraftMessage):
    """A message to send. The service sets From, Date and Message-ID. It
    needs a recipient, unless it is a reply: that finds one in the original."""

    @model_validator(mode="after")
    def _addressed(self) -> OutgoingMessage:
        replying = self.reference is not None and self.reference.action != "forward"
        if not self.recipients() and not replying:
            raise ValueError("a message needs at least one recipient")
        return self


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
