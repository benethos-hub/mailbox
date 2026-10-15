"""A message's bytes, parsed: which parts are its body and which are
attached."""

from __future__ import annotations

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
