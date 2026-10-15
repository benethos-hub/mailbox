"""A message's bytes, parsed: which parts are its body and which are
attached."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage

from benethos_mailbox_service.data.mail.parse import ParsedMessage


def _exchange_mail() -> EmailMessage:
    """As Exchange keeps a mail whose files were added one by one: the
    text of the body carries a Content-ID, seen live."""
    mail = EmailMessage()
    mail["Subject"] = "Large"
    mail.set_content("Hello")
    mail.add_alternative("<p>Hello</p>", subtype="html")
    for part in mail.iter_parts():
        part["Content-ID"] = f"<{part.get_content_subtype()}@example.com>"
    mail.add_attachment(b"%PDF", "application", "pdf", filename="offer.pdf")
    return mail


def test_a_body_with_a_content_id_is_no_attachment() -> None:
    parsed = ParsedMessage(_exchange_mail().as_bytes())
    assert [a.filename for a in parsed.attachments] == ["offer.pdf"]
    assert (parsed.text or "").strip() == "Hello"
    assert (parsed.html or "").strip() == "<p>Hello</p>"


def test_a_text_marked_as_an_attachment_stays_one() -> None:
    mail = EmailMessage()
    mail.set_content("Hello")
    mail.add_attachment("Notes", disposition="attachment", cid="<notes@example.com>")
    [notes] = ParsedMessage(mail.as_bytes()).attachments
    assert (notes.filename, notes.content_type) == (None, "text/plain")
    assert notes.payload.strip() == b"Notes"


def test_a_named_text_is_an_attachment() -> None:
    mail = EmailMessage()
    mail.set_content("Hello")
    mail.add_attachment("Notes", filename="notes.txt", disposition="inline")
    [notes] = ParsedMessage(mail.as_bytes()).attachments
    assert notes.filename == "notes.txt"


def test_an_image_in_the_html_is_listed() -> None:
    mail = EmailMessage()
    mail.set_content("Hello")
    mail.add_alternative('<p><img src="cid:logo@example.com"></p>', subtype="html")
    html = mail.get_payload()[1]
    html.add_related(b"\x89PNG", "image", "png", cid="<logo@example.com>")
    [image] = ParsedMessage(mail.as_bytes()).attachments
    assert image.content_type == "image/png" and not image.attached


def test_received_is_the_time_of_the_topmost_received_header() -> None:
    raw = (
        b"Received: from relay.example.org by mx.example.org;\r\n"
        b" Tue, 01 Sep 2026 12:00:05 +0200\r\n"
        b"Received: from client by relay.example.org;\r\n"
        b" Tue, 01 Sep 2026 09:59:00 +0000\r\n"
        b"Date: Tue, 01 Sep 2026 09:58:00 +0000\r\n"
        b"Subject: Hi\r\n\r\nHello\r\n"
    )
    assert ParsedMessage(raw).received == datetime(2026, 9, 1, 10, 0, 5, tzinfo=UTC)


def test_received_is_none_without_a_readable_header() -> None:
    assert ParsedMessage(b"Subject: Hi\r\n\r\nHello\r\n").received is None
    odd = b"Received: from relay.example.org; not a date\r\nSubject: Hi\r\n\r\n"
    assert ParsedMessage(odd).received is None
