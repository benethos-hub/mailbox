"""What the model must answer, and the text it is given.

The model answers whether a message is an invoice and, for one that is
not, which near miss it is, with a quote. It names no supplier and no
folder (prompt ``v4``): where an invoice goes follows from the folder it
lies in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...records import Attachment, MailMessage

__all__ = [
    "MAX_ADDRESS",
    "MAX_FILES",
    "MAX_FILES_TEXT",
    "MAX_NAME",
    "MAX_SUBJECT",
    "MAX_TEXT",
    "Answer",
    "parts",
    "render",
]

# The text of a mail is cut here. An invoice says what it is near the top.
MAX_TEXT = 6000

# The sender's name and the subject are cut here, the attachments listed
# are the first ones that fit both limits. A stranger chooses all of them,
# so no mail can blow up a call. The same cut goes to the model and to the
# evidence check.
MAX_SUBJECT = 300
MAX_NAME = 300
# The sender's address is cut here: 64 characters before the @, 255
# after it, as much as the mail standards allow. A longer one is no
# address a server delivers, and only blows up the call.
MAX_ADDRESS = 320
MAX_FILES = 20
MAX_FILES_TEXT = 1000


class Answer(BaseModel):
    """The answer of the model."""

    model_config = ConfigDict(extra="forbid")

    label: Literal["invoice", "other"]
    near_miss: Literal[
        "reminder", "quotation", "order_confirmation", "payment_receipt", "none"
    ]
    quote: str


def render(message: MailMessage) -> str:
    """The content of one call: sender, subject, attachments, text."""
    lines = []
    if message.sender is not None:
        lines.append(f"From: {_named(message)}")
    lines.append(f"Subject: {_subject(message)}")
    files = _files(message)
    if files:
        lines.append(f"Attachments: {', '.join(_file(a) for a in files)}")
    return "\n".join(lines) + "\n\n" + message.text[:MAX_TEXT]


def parts(message: MailMessage) -> list[str]:
    """The parts of the mail :func:`render` gives the model, without its
    frame: what a quote is looked up in."""
    files = [a.filename for a in _files(message) if a.filename]
    return [_named(message), _subject(message), *files, message.text[:MAX_TEXT]]


def _named(message: MailMessage) -> str:
    sender = message.sender
    if sender is None:
        return ""
    name = (sender.name or "")[:MAX_NAME]
    email = sender.email[:MAX_ADDRESS]
    return f"{name} <{email}>" if name else email


def _subject(message: MailMessage) -> str:
    return (message.subject or "")[:MAX_SUBJECT]


def _file(attachment: Attachment) -> str:
    return f"{attachment.filename or '(no name)'} ({attachment.content_type})"


def _files(message: MailMessage) -> list[Attachment]:
    """The attachments named: the first :data:`MAX_FILES`, as long as
    their line stays within :data:`MAX_FILES_TEXT` characters."""
    kept: list[Attachment] = []
    size = 0
    for attachment in message.attachments[:MAX_FILES]:
        size += len(_file(attachment)) + (2 if kept else 0)
        if size > MAX_FILES_TEXT:
            break
        kept.append(attachment)
    return kept
