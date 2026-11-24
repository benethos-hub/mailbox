"""What the model must answer, and the text it is given.

The model answers which of the groups to choose from a message belongs
to, or ``none``, with a quote (prompt ``v1``). It names a group of the
list, never a folder. The groups to choose from, each with its name and
its topic, follow the fixed text of the prompt, so the answer model is
made for them: its ``group`` is one of their names or ``none``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, create_model

from ...records import Attachment, MailMessage
from .groups import NONE, Group

__all__ = [
    "MAX_ADDRESS",
    "MAX_FILES",
    "MAX_FILES_TEXT",
    "MAX_NAME",
    "MAX_SUBJECT",
    "MAX_TEXT",
    "answer_for",
    "parts",
    "render",
    "system_for",
]

# The text of a mail is cut here.
MAX_TEXT = 6000

# The sender's name and the subject are cut here, the attachments listed
# are the first ones that fit both limits. A stranger chooses all of them,
# so no mail can blow up a call. The same cut goes to the model and to the
# evidence check.
MAX_SUBJECT = 300
MAX_NAME = 300
# The sender's address is cut here: 64 characters before the @, 255
# after it, as much as the mail standards allow.
MAX_ADDRESS = 320
MAX_FILES = 20
MAX_FILES_TEXT = 1000


def answer_for(names: Sequence[str]) -> type[BaseModel]:
    """The answer model for the groups called ``names``: ``group`` is one
    of them or ``none``, and ``quote`` the passage that shows it."""
    choice = cast(Any, Literal)[(*names, NONE)]
    return create_model(
        "Answer",
        __config__=ConfigDict(extra="forbid"),
        group=(choice, ...),
        quote=(str, ...),
    )


def system_for(prompt: str, groups: Sequence[Group]) -> str:
    """The system text of one call: the fixed text of the prompt, and
    under it a line for each group to choose from, its name and its
    topic."""
    lines = [f"- {group.name}: {group.topic}" for group in groups]
    return prompt.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n"


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
    frame: what a quote is looked up in. The topics are no part of it, so
    a quote from them is not found."""
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
