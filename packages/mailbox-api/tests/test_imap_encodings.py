"""The traps of CONCEPT 5.10, each with a fixture of its own."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from imap_tools.folder import MailBoxFolderManager
from pydantic import SecretStr

from benethos_mailbox_api.data.models import FolderRole
from benethos_mailbox_api.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_api.data.providers.imap.client import (
    ImapServer,
    ImapSession,
    RawFolder,
)

from .imap_fake import FakeMailBox

# --- folder names in modified UTF-7, decoded by the real library -----------------


class _RawListClient:
    """Answers LIST and SELECT the way imaplib hands a server's reply over."""

    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines
        self.selected: list[bytes | str] = []

    def _simple_command(self, command: str, *args: Any) -> tuple[str, list[bytes]]:
        return "OK", self.lines

    def _untagged_response(
        self, typ: str, data: list[bytes], command: str
    ) -> tuple[str, list[bytes]]:
        return typ, data

    def select(self, folder: bytes | str, readonly: bool) -> tuple[str, list[bytes]]:
        self.selected.append(folder)
        return "OK", [b"1"]


class _RawMailBox:
    def __init__(self, lines: list[bytes]) -> None:
        self.client = _RawListClient(lines)
        self.folder = MailBoxFolderManager(self)

    def login(self, *args: Any, **kwargs: Any) -> None:
        return None


LIST_REPLY = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren) "/" "Entw&APw-rfe"',
    b'(\\HasNoChildren) "/" "Gel&APY-schte Elemente"',
    b'(\\HasChildren) "/" "Kunden"',
    b'(\\HasNoChildren) "/" "Kunden/M&APw-ller GmbH"',
]


def _session(lines: list[bytes]) -> tuple[ImapSession, _RawMailBox]:
    box = _RawMailBox(lines)
    session = ImapSession(
        ImapServer("imap.example.com", 993, "tls"), mailbox_factory=lambda s, t: box
    )
    session.login("me", "secret")
    return session, box


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
    session, box = _session(LIST_REPLY)
    box.folder.status = lambda folder, options: {"UIDVALIDITY": 1}  # type: ignore[method-assign]
    session.select("Entwürfe")
    assert box.client.selected == [b'"Entw&APw-rfe"']


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
        session_factory=lambda s: ImapSession(s, mailbox_factory=box),
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
    assert mappers.unicode_address("me@example.com") == "me@example.com"
    assert mappers.unicode_address("no-at-sign") == "no-at-sign"
    assert mappers.unicode_address("x@xn--.de") == "x@xn--.de"
