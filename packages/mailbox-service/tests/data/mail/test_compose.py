"""A composed message taken apart for a provider that takes its
attachments one by one."""

from __future__ import annotations

from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default

from benethos_mailbox_service.data.mail import compose


def test_the_files_come_off_and_the_rest_stays() -> None:
    mail = EmailMessage()
    mail["Subject"] = "Plan"
    mail["Message-ID"] = "<plan@example.com>"
    mail.set_content("Hello")
    mail.add_alternative("<p>Hello</p>", subtype="html")
    mail.add_attachment(b"%PDF", "application", "pdf", filename="offer.pdf")
    forwarded = EmailMessage()
    forwarded["Subject"] = "Earlier"
    forwarded.set_content("Before")
    mail.add_attachment(forwarded, filename="forwarded.eml")
    rest, files = compose.without_attachments(mail.as_bytes())
    left = message_from_bytes(rest, policy=default)
    assert left["Message-ID"] == "<plan@example.com>"
    assert list(left.iter_attachments()) == []
    body = left.get_body(("plain",))
    assert body is not None and body.get_content().strip() == "Hello"
    pdf, eml = files
    assert (pdf.filename, pdf.content_type, pdf.data) == (
        "offer.pdf",
        "application/pdf",
        b"%PDF",
    )
    assert eml.content_type == "message/rfc822"
    assert message_from_bytes(eml.data, policy=default)["Subject"] == "Earlier"


def test_a_body_left_alone_is_the_whole_message() -> None:
    """Not a multipart/mixed of one part: Exchange then listed the text as
    a nameless attachment, seen live."""
    mail = EmailMessage()
    mail["Subject"] = "Plan"
    mail.set_content("Hello")
    mail.add_attachment(b"%PDF", "application", "pdf", filename="offer.pdf")
    rest, [pdf] = compose.without_attachments(mail.as_bytes())
    left = message_from_bytes(rest, policy=default)
    assert left.get_content_type() == "text/plain"
    assert left["Subject"] == "Plan"
    assert left.get_content().strip() == "Hello"
    assert pdf.filename == "offer.pdf"


def test_a_message_without_files_stays_as_it_is() -> None:
    raw = b"Subject: Plan\r\nContent-Type: text/plain\r\n\r\nHello\r\n"
    assert compose.without_attachments(raw) == (raw, [])
