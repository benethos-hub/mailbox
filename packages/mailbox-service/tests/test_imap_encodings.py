"""The traps of CONCEPT 5.10, each with a fixture of its own."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from imapclient import testable_imapclient
from pydantic import SecretStr

from benethos_mailbox_service.data.mail import convert, fields
from benethos_mailbox_service.data.mail.parse import ParsedMessage
from benethos_mailbox_service.data.models import FolderRole
from benethos_mailbox_service.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_service.data.providers.protocols.imap import (
    ImapServer,
    ImapSession,
    RawFolder,
)

from .imap_fake import FakeMailBox

# --- folder names in modified UTF-7, decoded by the real library -----------------


def _raw_client(lines: list[bytes]) -> Any:
    """The real IMAPClient over imaplib's replies as the server sent them,
    with IMAPClient's own test double in place of the connection."""
    client = testable_imapclient.TestableIMAPClient()
    imap = client._imap
    imap.login.return_value = ("OK", [b"Logged in"])
    imap._simple_command.return_value = ("OK", [b"LIST done"])
    imap._untagged_response.return_value = ("OK", lines)
    imap.select.return_value = ("OK", [b"1"])
    imap.untagged_responses = {"UIDVALIDITY": [b"1"]}
    return client


LIST_REPLY = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren) "/" "Entw&APw-rfe"',
    b'(\\HasNoChildren) "/" "Gel&APY-schte Elemente"',
    b'(\\HasChildren) "/" "Kunden"',
    b'(\\HasNoChildren) "/" "Kunden/M&APw-ller GmbH"',
]


def _session(lines: list[bytes]) -> tuple[ImapSession, Any]:
    client = _raw_client(lines)
    session = ImapSession(
        ImapServer("imap.example.com", 993, "tls"),
        client_factory=lambda s, t: client,
    )
    session.login("me", "secret")
    return session, client


def test_folder_names_are_decoded() -> None:
    session, _ = _session(LIST_REPLY)
    names = [raw.name for raw in session.list_folders()]
    assert names == [
        "INBOX",
        "Entwürfe",
        "Gelöschte Elemente",
        "Kunden",
        "Kunden/Müller GmbH",
    ]


def test_localised_special_folders_get_their_roles() -> None:
    session, _ = _session(LIST_REPLY)
    folders = {f.name: f for f in mappers.to_folders(session.list_folders())}
    assert folders["Entwürfe"].role is FolderRole.DRAFTS
    assert folders["Gelöschte Elemente"].role is FolderRole.TRASH
    assert folders["Müller GmbH"].role is None
    assert folders["Müller GmbH"].parent_id == mappers.folder_id("Kunden")


def test_selecting_encodes_the_name_again() -> None:
    session, client = _session(LIST_REPLY)
    assert session.select("Entwürfe") == 1
    folder = client._imap.select.call_args.args[0]
    assert folder == b'"Entw&APw-rfe"'


def test_flags_win_over_names() -> None:
    folders = {
        f.name: f
        for f in mappers.to_folders(
            [
                RawFolder("INBOX", ".", ()),
                RawFolder("INBOX.Sent Items", ".", ("\\Sent",)),
                RawFolder("INBOX.Gesendet", ".", ()),
                RawFolder("INBOX.Spam", ".", ()),
                RawFolder("INBOX.Archiv", ".", ()),
            ]
        )
    }
    assert folders["Sent Items"].role is FolderRole.SENT
    assert folders["Gesendet"].role is None  # the flag claimed the role
    assert folders["Spam"].role is FolderRole.JUNK
    assert folders["Archiv"].role is FolderRole.ARCHIVE


def test_only_the_first_folder_with_a_name_gets_the_role() -> None:
    folders = mappers.to_folders(
        [RawFolder("Trash", "/", ()), RawFolder("Papierkorb", "/", ())]
    )
    assert [f.role for f in folders] == [FolderRole.TRASH, None]


# --- headers, charsets, domains and dates ---------------------------------------------

BROKEN = (
    b"Subject: =?iso-8859-1?Q?Gr=FC=DFe_aus_K=F6ln?=\r\n"
    b"From: =?utf-8?Q?B=C3=BCcherei?= <info@xn--bcher-kva.de>\r\n"
    b"To: me@example.com\r\n"
    b"Date: Tue, 01 Sep 2026 10:00:00\r\n"
    b"Content-Type: text/plain; charset=x-unknown-charset\r\n"
    b"\r\n"
    b"Stra\xc3\x9fe und Gr\xc3\xbc\xc3\x9fe\r\n"
)


def _provider(box: FakeMailBox) -> ImapProvider:
    return ImapProvider(
        {"host": "imap.example.com", "username": "me"},
        lambda field: SecretStr("secret"),
        session_factory=lambda s: ImapSession(s, client_factory=box),
    )


async def test_broken_charsets_idn_and_zoneless_dates() -> None:
    box = FakeMailBox()
    box.add("INBOX", 1, BROKEN)
    message = await _provider(box).get_message(mappers.message_id("INBOX", 1, 1))
    assert message.subject == "Grüße aus Köln"
    assert message.sender is not None
    assert message.sender.name == "Bücherei"
    assert message.sender.email == "info@bücher.de"
    assert message.date == datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    assert message.text_body is not None
    assert "Stra" in message.text_body


def test_unicode_address_leaves_plain_and_broken_domains_alone() -> None:
    assert fields.unicode_address("me@example.com") == "me@example.com"
    assert fields.unicode_address("no-at-sign") == "no-at-sign"
    assert fields.unicode_address("x@xn--.de") == "x@xn--.de"


# --- thread headers, folded by the sender ---------------------------------------------


def test_a_folded_in_reply_to_comes_unfolded() -> None:
    raw = (
        b"Subject: Re: Plan\r\nMessage-ID:\r\n <b@example.com>\r\n"
        b"In-Reply-To: <a@example.com>\r\n <older@example.com>\r\n\r\nYes\r\n"
    )
    fields_of = convert.thread_fields(ParsedMessage(raw))
    assert fields_of["message_id_header"] == "<b@example.com>"
    assert fields_of["in_reply_to"] == "<a@example.com>"


# --- what counts as an attachment -----------------------------------------------------


def _html_with_image() -> bytes:
    mail = EmailMessage()
    mail["Subject"] = "Newsletter"
    mail.set_content("Hello")
    mail.add_alternative('<p>Hello <img src="cid:logo"></p>', subtype="html")
    html = mail.get_payload()[1]
    html.add_related(b"\x89PNG", maintype="image", subtype="png", cid="<logo>")
    return mail.as_bytes()


def _inline_pdf() -> bytes:
    mail = EmailMessage()
    mail["Subject"] = "Invoice"
    mail.set_content("Attached")
    mail.add_attachment(
        b"%PDF", maintype="application", subtype="pdf", filename="invoice.pdf"
    )
    part = mail.get_payload()[1]
    part.replace_header("Content-Disposition", 'inline; filename="invoice.pdf"')
    return mail.as_bytes()


def test_an_image_the_html_shows_is_no_attachment() -> None:
    parsed = ParsedMessage(_html_with_image())
    opened = convert.message_fields(parsed)
    assert len(opened["attachments"]) == 1  # listed, to be fetched by cid
    assert opened["has_attachments"] is False
    assert convert.summary_fields(parsed)["has_attachments"] is False


def test_a_file_marked_inline_is_an_attachment() -> None:
    parsed = ParsedMessage(_inline_pdf())
    assert convert.message_fields(parsed)["has_attachments"] is True
    assert convert.summary_fields(parsed)["has_attachments"] is True
