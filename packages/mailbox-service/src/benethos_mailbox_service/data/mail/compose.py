"""An outgoing message as RFC 5322 bytes, with the standard library's
``email``. Translates, decides nothing: who sends, when and under which
Message-ID comes from the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.parser import BytesHeaderParser, BytesParser
from email.policy import SMTP, default
from email.utils import format_datetime, formataddr, getaddresses, make_msgid
from html import escape
from typing import NamedTuple

from pydantic import ValidationError

from ..models import Address, DraftMessage, Message, MessageReference, Recipient
from .fields import ascii_domain
from .fields import message_id as one_message_id
from .text import from_html

# Where a draft keeps what it answers, e.g. ``reply msg_...``, until it is sent.
REFERENCE_HEADER = "X-Mailbox-Service-Reference"


def write_reference(reference: MessageReference) -> str:
    """What a draft keeps of its reference until it is sent: the action and
    the original's id, e.g. ``reply msg_...``."""
    return f"{reference.action} {reference.message_id}"


def read_reference(value: str | None) -> MessageReference | None:
    """The reference a draft kept. None for anything else, such as a header
    another mail client changed."""
    if not value:
        return None
    action, _, message_id = value.strip().partition(" ")
    try:
        return MessageReference(action=action, message_id=message_id.strip())
    except ValidationError:
        return None


def new_message_id(sender_email: str) -> str:
    """A fresh ``Message-ID`` in the sender's domain."""
    return make_msgid(domain=sender_email.rpartition("@")[2] or None)


@dataclass(frozen=True)
class Extras:
    """What a reply or a forward adds to a message."""

    in_reply_to: str | None = None
    references: tuple[str, ...] = ()
    # (filename, content type, data) of the original's attachments.
    attachments: tuple[tuple[str, str, bytes], ...] = ()
    # The original itself, attached as message/rfc822.
    attached_message: bytes | None = None


def message(
    message: DraftMessage,
    sender: Recipient,
    date: datetime,
    message_id: str,
    extras: Extras = Extras(),  # noqa: B008 (frozen, shared safely)
    *,
    draft: bool = False,
    reference: str | None = None,
) -> bytes:
    """The message with CRLF line ends, ready for SMTP and IMAP APPEND.
    Bcc recipients appear in no header.

    A ``draft`` keeps its Bcc recipients, and ``reference`` in a header of
    its own. ``outgoing`` takes both out again before the draft is sent."""
    # 7bit: a body beyond ASCII is encoded, since the message is handed to
    # SMTP servers without asking for 8BITMIME.
    mail = EmailMessage(policy=SMTP.clone(cte_type="7bit"))
    mail["From"] = _address(sender)
    # Values that came out of another message, the original of a reply or a
    # forward, are folded onto one line here. What a caller wrote was checked
    # on the way in.
    if message.to:
        mail["To"] = ", ".join(_address(r) for r in message.to)
    if message.cc:
        mail["Cc"] = ", ".join(_address(r) for r in message.cc)
    if draft and message.bcc:
        mail["Bcc"] = ", ".join(_address(r) for r in message.bcc)
    if draft and reference:
        mail[REFERENCE_HEADER] = reference
    if message.reply_to:
        mail["Reply-To"] = ", ".join(_address(r) for r in message.reply_to)
    mail["Subject"] = one_line(message.subject)
    # RFC 5322 requires both. Without Date clients show no date.
    mail["Date"] = format_datetime(date)
    mail["Message-ID"] = message_id
    if extras.in_reply_to:
        mail["In-Reply-To"] = extras.in_reply_to
    if extras.references:
        mail["References"] = " ".join(extras.references)

    mail.set_content(body_text(message))
    if message.html is not None:
        mail.add_alternative(message.html, subtype="html")
    files = [(a.filename, a.content_type, a.data) for a in message.attachments]
    for filename, content_type, data in [*extras.attachments, *files]:
        maintype, _, subtype = one_line(content_type).partition("/")
        mail.add_attachment(
            data, maintype=maintype, subtype=subtype, filename=one_line(filename)
        )
    if extras.attached_message is not None:
        original = message_from_bytes(extras.attached_message, policy=default)
        mail.add_attachment(original, filename="forwarded.eml")
    return mail.as_bytes()


def body_text(message: DraftMessage) -> str:
    """The text part: ``text``, or for a message written as HTML only, the
    text made from its HTML, for clients that show text alone."""
    if message.text:
        return message.text
    return from_html(message.html) if message.html else ""


class Outgoing(NamedTuple):
    """A stored draft made ready to send."""

    raw: bytes
    recipients: list[str]  # To, Cc and Bcc, each once
    reference: str | None  # what the draft kept, e.g. ``reply msg_...``
    message_id: str


def outgoing(draft: bytes, date: datetime, message_id: str) -> Outgoing:
    """``draft`` dated ``date``, without its Bcc and reference headers.
    ``message_id`` is used where the draft has none, as one another mail
    client made may lack it."""
    mail = BytesParser(policy=SMTP).parsebytes(draft)
    fields = [str(v) for name in ("To", "Cc", "Bcc") for v in mail.get_all(name, [])]
    recipients = list(dict.fromkeys(a for _, a in getaddresses(fields) if a))
    reference = mail.get(REFERENCE_HEADER)
    del mail["Bcc"]
    del mail[REFERENCE_HEADER]
    del mail["Date"]
    mail["Date"] = format_datetime(date)
    kept = one_message_id(mail.get("Message-ID"))
    if kept is None:
        mail["Message-ID"] = message_id
    return Outgoing(
        mail.as_bytes(),
        recipients,
        str(reference) if reference else None,
        kept or message_id,
    )


# --- replies and forwards --------------------------------------------------------


def references(original_raw: bytes) -> tuple[str | None, tuple[str, ...]]:
    """The original's Message-ID, and the References a reply carries: the
    original's own, then its Message-ID (RFC 5322 3.6.4)."""
    headers = BytesHeaderParser(policy=default).parsebytes(original_raw)
    message_id = one_message_id(headers.get("Message-ID"))
    chain = tuple(str(headers.get("References") or "").split())
    if not chain:
        chain = tuple(str(headers.get("In-Reply-To") or "").split()[:1])
    return message_id, (*chain, message_id) if message_id else chain


def one_line(value: str) -> str:
    """``value`` on one line: every line break, including the Unicode ones
    the standard library refuses in a header, becomes a space."""
    return " ".join(value.splitlines())


def prefixed(prefix: str, subject: str | None) -> str:
    """``Re: Subject`` or ``Fwd: Subject``, not ``Re: Re: Subject``. On one
    line, whatever the original's subject carried."""
    subject = one_line(subject or "").strip()
    if subject.lower().startswith(prefix.lower()):
        return subject
    return f"{prefix} {subject}".strip()


def quoted(original: Message, text: str | None) -> str:
    """The reply's text above the original, quoted with ``> ``."""
    when = format_datetime(original.date) if original.date else "an unknown date"
    who = _who(original.sender)
    lines = (original.text_body or "").splitlines() or [""]
    quote = "\n".join(f"> {line}" if line else ">" for line in lines)
    return f"{text or ''}\n\nOn {when}, {who} wrote:\n{quote}\n"


def forwarded(original: Message, text: str | None) -> str:
    """The forward's text above the original with its headers, the way
    common mail clients write it."""
    block = [
        "---------- Forwarded message ----------",
        f"From: {_who(original.sender)}",
        f"Date: {format_datetime(original.date) if original.date else '-'}",
        f"Subject: {original.subject or ''}",
        f"To: {', '.join(_who(a) for a in original.to) or '-'}",
    ]
    if original.cc:
        block.append(f"Cc: {', '.join(_who(a) for a in original.cc)}")
    return f"{text or ''}\n\n" + "\n".join(block) + f"\n\n{original.text_body or ''}\n"


def quoted_html(original: Message, html: str, heading: str) -> str:
    """The reply's or forward's HTML above the original in a blockquote."""
    body = original.html_body or f"<pre>{escape(original.text_body or '')}</pre>"
    return (
        f"{html}<br><div>{escape(heading)}</div>"
        f'<blockquote style="margin:0 0 0 .8ex;border-left:1px solid #ccc;'
        f'padding-left:1ex">{body}</blockquote>'
    )


def _who(address: Address | None) -> str:
    return _formatted(address.name, address.email) if address else "unknown"


def with_bcc(raw: bytes, recipients: list[str]) -> bytes:
    """``raw`` with a Bcc header for the recipients no header names, for a
    provider that reads the recipients from the message itself."""
    head, separator, body = raw.partition(b"\r\n\r\n")
    headers = BytesHeaderParser(policy=default).parsebytes(head + separator)
    named = {
        address.lower()
        for _, address in getaddresses(
            [str(v) for n in ("To", "Cc", "Bcc") for v in headers.get_all(n, [])]
        )
    }
    hidden = [ascii_domain(r) for r in recipients if r.lower() not in named]
    if not hidden:
        return raw
    return head + b"\r\nBcc: " + ", ".join(hidden).encode() + separator + body


def _address(recipient: Recipient) -> str:
    return _formatted(recipient.name, recipient.email)


def _formatted(name: str | None, email: str) -> str:
    """``Name <address>``, the name on one line whatever message it came from."""
    return formataddr((one_line(name or ""), email))
