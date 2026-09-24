"""An outgoing message as RFC 5322 bytes, with the standard library's
``email``. Translates, decides nothing: who sends, when and under which
Message-ID comes from the caller.
"""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, formataddr, make_msgid

from .models import OutgoingMessage, Recipient


def new_message_id(sender_email: str) -> str:
    """A fresh ``Message-ID`` in the sender's domain."""
    return make_msgid(domain=sender_email.rpartition("@")[2] or None)


def compose(
    message: OutgoingMessage,
    sender: Recipient,
    date: datetime,
    message_id: str,
) -> bytes:
    """The message with CRLF line ends, ready for SMTP and IMAP APPEND.
    Bcc recipients appear in no header."""
    mail = EmailMessage(policy=SMTP)
    mail["From"] = _address(sender)
    if message.to:
        mail["To"] = ", ".join(_address(r) for r in message.to)
    if message.cc:
        mail["Cc"] = ", ".join(_address(r) for r in message.cc)
    if message.reply_to:
        mail["Reply-To"] = ", ".join(_address(r) for r in message.reply_to)
    mail["Subject"] = message.subject
    # RFC 5322 requires both. Without Date clients show no date.
    mail["Date"] = format_datetime(date)
    mail["Message-ID"] = message_id

    mail.set_content(message.text or "")
    if message.html is not None:
        mail.add_alternative(message.html, subtype="html")
    for attachment in message.attachments:
        maintype, _, subtype = attachment.content_type.partition("/")
        mail.add_attachment(
            attachment.data,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    return mail.as_bytes()


def _address(recipient: Recipient) -> str:
    return formataddr((recipient.name or "", recipient.email))
