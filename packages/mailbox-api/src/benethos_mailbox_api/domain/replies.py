"""Replies and forwards (CONCEPT 6.4), made from the original: recipients
where the caller named none, subject, quote and what goes with it.

Pure functions: the mailbox service fetches the original, these decide what
the answer looks like.
"""

from __future__ import annotations

from typing import Any, TypeVar

from ..data.mail import compose
from ..data.models import DraftMessage, Message, MessageReference, Recipient
from ..errors import BadRequestError

# (filename, content type, data) of one of the original's attachments.
AttachedFile = tuple[str, str, bytes]

# A message to send or a draft: what goes in comes out, filled in.
M = TypeVar("M", bound=DraftMessage)


def reply(
    message: M,
    action: str,
    original: Message,
    raw: bytes,
    own_address: str,
) -> tuple[M, compose.Extras]:
    """``reply`` or ``reply_all``, in the original's thread."""
    in_reply_to, chain = compose.references(raw)
    changes: dict[str, Any] = {
        "subject": message.subject or compose.prefixed("Re:", original.subject),
        "text": compose.quoted(original, message.text),
    }
    if message.html is not None:
        changes["html"] = compose.quoted_html(
            original, message.html, "Original message"
        )
    if not message.recipients():
        changes.update(_recipients(original, action, own_address))
    return (
        message.model_copy(update=changes),
        compose.Extras(in_reply_to=in_reply_to, references=chain),
    )


def forward(
    message: M,
    forward_as: str,
    original: Message,
    raw: bytes,
    files: list[AttachedFile],
) -> tuple[M, compose.Extras]:
    """``inline``: quoted with its headers, ``files`` attached.
    ``attachment``: the unchanged original as ``message/rfc822``."""
    changes: dict[str, Any] = {
        "subject": message.subject or compose.prefixed("Fwd:", original.subject)
    }
    if forward_as == "attachment":
        return message.model_copy(update=changes), compose.Extras(attached_message=raw)
    changes["text"] = compose.forwarded(original, message.text)
    if message.html is not None:
        changes["html"] = compose.quoted_html(
            original, message.html, "Forwarded message"
        )
    return message.model_copy(update=changes), compose.Extras(attachments=tuple(files))


def answered_keyword(reference: MessageReference) -> str:
    """The keyword the original gets, so other clients show it too."""
    return "$forwarded" if reference.action == "forward" else "$answered"


def _recipients(
    original: Message, action: str, own_address: str
) -> dict[str, list[Recipient]]:
    """To the original's Reply-To, else its sender; for reply_all also to
    everyone it went to, except this account."""
    first = original.reply_to or ([original.sender] if original.sender else [])
    to = [Recipient(email=a.email, name=a.name) for a in first]
    cc: list[Recipient] = []
    if action == "reply_all":
        seen = {own_address.lower(), *(r.email.lower() for r in to)}
        for address in (*original.to, *original.cc):
            if address.email.lower() not in seen:
                seen.add(address.email.lower())
                cc.append(Recipient(email=address.email, name=address.name))
    if not to and not cc:
        raise BadRequestError("the original names nobody to reply to")
    return {"to": to, "cc": cc}
