"""A message's bytes, parsed: which parts are its body and which are
attached."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from benethos_mailbox_service.data.mail import authentication, convert
from benethos_mailbox_service.data.mail.parse import (
    ParsedMessage,
    PartShape,
    has_attachments,
)


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


def test_what_counts_as_an_attachment() -> None:
    """UNIFORM 6.10: a part the body does not show in its place."""
    shape = PartShape
    # Apple Mail marks a PDF inline: it is a file all the same.
    assert has_attachments([shape("application/pdf", "a.pdf", "inline")])
    assert has_attachments([shape("image/png", "x.png", "attachment", "<x@y>")])
    assert has_attachments([shape("message/rfc822")])
    assert not has_attachments([shape("image/png", None, "inline", "<x@y>")])
    assert not has_attachments(
        [shape("text/plain"), shape("text/html", None, "inline")]
    )
    assert not has_attachments([shape("application/pdf")])


def _labelled(subtype: str, charset: str, body: bytes) -> bytes:
    """A message of one text part, its bytes quoted-printable under the
    label ``charset``, whatever they really are."""
    head = (
        "From: billing@example.com\r\nSubject: Ihre Rechnung\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: text/{subtype}; charset={charset}\r\n"
        "Content-Transfer-Encoding: quoted-printable\r\n\r\n"
    )
    return head.encode("ascii") + body + b"\r\n"


def test_utf_8_under_a_western_label_reads_as_utf_8() -> None:
    mail = EmailMessage()
    mail["From"] = "billing@example.com"
    mail.set_content("Ihre Rechnung für Oktober")
    mail.add_alternative("<p>Ihre Rechnung für Oktober</p>", subtype="html")
    plain = mail.get_payload()[0]
    plain.set_param("charset", "windows-1252")
    raw = mail.as_bytes()
    assert "f\u00fcr".encode() in raw
    parsed = ParsedMessage(raw)
    assert (parsed.text or "").strip() == "Ihre Rechnung für Oktober"
    assert (parsed.html or "").strip() == "<p>Ihre Rechnung für Oktober</p>"


@pytest.mark.parametrize(
    "charset", ["windows-1252", "iso-8859-1", "latin-1", "iso-8859-15", "us-ascii"]
)
@pytest.mark.parametrize("subtype", ["plain", "html"])
def test_a_wrong_label_on_utf_8_is_set_right(charset: str, subtype: str) -> None:
    parsed = ParsedMessage(_labelled(subtype, charset, b"Ihre Rechnung f=C3=BCr"))
    body = parsed.text if subtype == "plain" else parsed.html
    assert (body or "").strip() == "Ihre Rechnung für"


@pytest.mark.parametrize("charset", ["windows-1252", "iso-8859-1", "iso-8859-15"])
def test_text_in_its_western_charset_stays_as_it_is(charset: str) -> None:
    # "ü" is the byte FC, which alone is no UTF-8.
    parsed = ParsedMessage(_labelled("plain", charset, b"Ihre Rechnung f=FCr"))
    assert (parsed.text or "").strip() == "Ihre Rechnung für"


@pytest.mark.parametrize("charset", ["windows-1252", "utf-8", "gb2312", "x-unknown"])
def test_ascii_stays_as_it_is_under_any_label(charset: str) -> None:
    parsed = ParsedMessage(_labelled("plain", charset, b"Invoice for October"))
    assert (parsed.text or "").strip() == "Invoice for October"


def test_a_multi_byte_label_is_left_alone() -> None:
    chinese = "中文".encode("gb2312")
    quoted = "".join(f"={b:02X}" for b in chinese).encode("ascii")
    assert (ParsedMessage(_labelled("plain", "gb2312", quoted)).text or "").strip() == (
        "中文"
    )
    # UTF-8 under a multi-byte label is read by the label, as before.
    utf8 = b"f=C3=BCr"
    read = ParsedMessage(_labelled("plain", "gb2312", utf8)).text or ""
    assert read.strip() == "für".encode().decode("gb2312", "ignore")
    japanese = "日本語".encode("iso-2022-jp")
    parsed = ParsedMessage(_labelled("plain", "iso-2022-jp", japanese))
    assert (parsed.text or "").strip() == "日本語"


def test_an_unknown_label_reads_as_utf_8() -> None:
    parsed = ParsedMessage(_labelled("plain", "x-unknown", b"f=C3=BCr"))
    assert (parsed.text or "").strip() == "für"


def test_every_value_of_a_header_and_the_one_sender() -> None:
    raw = (
        b"From: Ann <ann@example.com>\r\n"
        b"Authentication-Results: mx.example.org; dmarc=pass\r\n"
        b"Authentication-Results: mx.example.net; dmarc=fail\r\n"
        b"Subject: Hi\r\n\r\nHello\r\n"
    )
    parsed = ParsedMessage(raw)
    assert parsed.all_headers("authentication-results") == [
        "mx.example.org; dmarc=pass",
        "mx.example.net; dmarc=fail",
    ]
    assert parsed.all_headers("x-none") == []
    assert parsed.sole_sender == "ann@example.com"


@pytest.mark.parametrize("sender", [b"", b"From: a@example.com, b@example.com\r\n"])
def test_no_sole_sender(sender: bytes) -> None:
    raw = sender + b"Subject: Hi\r\n\r\nHello\r\n"
    assert ParsedMessage(raw).sole_sender is None


def test_a_from_read_two_ways_has_no_sole_sender() -> None:
    """A folded From after an open quote: the shown sender is one address,
    the raw header another. The check judges neither."""
    raw = (
        b"Authentication-Results: mx.example.org; dmarc=pass"
        b" header.from=evil.example\r\n"
        b'From: "a@bank.example""\r\n <b@evil.example>\r\n'
        b"Subject: x\r\n\r\nbody\r\n"
    )
    parsed = ParsedMessage(raw)
    trust = authentication.Trust(("mx.example.org",))
    assert convert.summary_fields(parsed, trust)["sender_check"].result != "pass"


def test_a_sole_sender_compares_without_case_and_in_ascii() -> None:
    raw = b"From: Ann <Ann@xn--bcher-kva.example>\r\nSubject: Hi\r\n\r\nHello\r\n"
    assert ParsedMessage(raw).sole_sender == "Ann@xn--bcher-kva.example"


def test_a_raw_utf_8_from_is_judged() -> None:
    """RFC 6532: an address beyond ASCII written raw in UTF-8."""
    raw = (
        "Authentication-Results: mx.example.org; dmarc=pass"
        " header.from=xn--bcher-kva.de\r\n"
        "From: Jörg <a@bücher.de>\r\nSubject: Hi\r\n\r\nHello\r\n"
    ).encode()
    parsed = ParsedMessage(raw)
    assert parsed.all_headers("from") == ["Jörg <a@bücher.de>"]
    trust = authentication.Trust(("mx.example.org",))
    found = convert.summary_fields(parsed, trust)["sender_check"]
    assert (found.result, found.domain) == ("pass", "xn--bcher-kva.de")
