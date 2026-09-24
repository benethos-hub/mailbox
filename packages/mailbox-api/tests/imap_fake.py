"""A stand-in for ``imap_tools.MailBox``: the same calls, answered from memory.

Messages are real RFC 822 bytes, so imap-tools does the real parsing. Only
the network is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from imap_tools import MailboxLoginError, MailMessage
from imap_tools.folder import FolderInfo


def make_message(
    subject: str,
    *,
    sender: str = "Alice Example <alice@example.com>",
    to: str = "me@example.com",
    date: datetime | None = None,
    text: str = "Hello",
    html: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Message-ID"] = f"<{abs(hash(subject))}@example.com>"
    if date is not None:
        msg["Date"] = format_datetime(date)
    for name, value in (extra_headers or {}).items():
        msg[name] = value
    msg.set_content(text)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    for filename, content_type, data in attachments or []:
        maintype, subtype = content_type.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


@dataclass
class FakeFolder:
    flags: tuple[str, ...] = ()
    uidvalidity: int = 1
    messages: dict[int, tuple[bytes, tuple[str, ...]]] = field(default_factory=dict)


class _FolderManager:
    def __init__(self, box: FakeMailBox) -> None:
        self._box = box

    def list(self) -> list[FolderInfo]:
        return [
            FolderInfo(name=name, delim=self._box.delimiter, flags=f.flags)
            for name, f in self._box.folders.items()
        ]

    def set(self, name: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self._box.calls.append(("select", name, readonly))
        if name not in self._box.folders:
            raise self._box.error("no such folder")
        self._box.selected = name
        return ("OK", [b""])

    def status(self, name: str, options: list[str]) -> dict[str, int]:
        return {"UIDVALIDITY": self._box.folders[name].uidvalidity}


class _Client:
    def __init__(self, box: FakeMailBox) -> None:
        self._box = box

    def uid(self, command: str, uid: str, parts: str) -> tuple[str, list[Any]]:
        self._box.calls.append(("uid", command, uid, parts))
        assert "PEEK" in parts, "a read must never set \\Seen"
        folder = self._box.folders[self._box.selected]
        entry = folder.messages.get(int(uid))
        if entry is None:
            return ("OK", [None])
        return (
            "OK",
            [(f"1 (UID {uid} BODY[] {{{len(entry[0])}}}".encode(), entry[0]), b")"],
        )


class FakeMailBox:
    """Shared across sessions of one test, like a server."""

    def __init__(self, password: str = "secret") -> None:
        self.password = password
        self.delimiter = "/"
        self.folders: dict[str, FakeFolder] = {"INBOX": FakeFolder()}
        self.selected = "INBOX"
        self.calls: list[tuple[Any, ...]] = []
        self.logins = 0
        self.fail_next: Exception | None = None
        self.folder = _FolderManager(self)
        self.client = _Client(self)
        self.error = RuntimeError

    # the factory signature ImapSession expects
    def __call__(self, server: Any, timeout: float) -> FakeMailBox:
        self.calls.append(("connect", server.host, server.port, server.security))
        return self

    def add(
        self, folder: str, uid: int, raw: bytes, flags: tuple[str, ...] = ()
    ) -> None:
        self.folders.setdefault(folder, FakeFolder()).messages[uid] = (raw, flags)

    def login(
        self, username: str, password: str, initial_folder: str | None = None
    ) -> None:
        self.calls.append(("login", username))
        if password != self.password:
            raise MailboxLoginError(("NO", [b"authentication failed"]), "OK")
        self.logins += 1

    def xoauth2(
        self, username: str, token: str, initial_folder: str | None = None
    ) -> None:
        self.calls.append(("xoauth2", username))
        if token != self.password:
            raise MailboxLoginError(("NO", [b"invalid token"]), "OK")
        self.logins += 1

    def logout(self) -> None:
        self.calls.append(("logout",))

    def uids(self, query: Any, charset: str | None = None) -> list[str]:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        self.calls.append(("search", str(query), charset))
        folder = self.folders[self.selected]
        text = str(query)
        result = []
        for uid, (raw, flags) in folder.messages.items():
            if "UNSEEN" in text and "\\Seen" in flags:
                continue
            if re.search(r"(?<!UN)SEEN", text) and "\\Seen" not in flags:
                continue
            match = re.search(r'TEXT "([^"]*)"', text)
            if (
                match
                and match.group(1).lower() not in raw.decode(errors="replace").lower()
            ):
                continue
            result.append(str(uid))
        return result

    def fetch(
        self,
        uid_list: list[str],
        headers_only: bool = False,
        mark_seen: bool = True,
        bulk: bool = False,
        **_: Any,
    ) -> list[MailMessage]:
        assert mark_seen is False, "a read must never set \\Seen"
        self.calls.append(("fetch", tuple(uid_list), headers_only))
        folder = self.folders[self.selected]
        found = []
        for uid in uid_list:
            entry = folder.messages.get(int(uid))
            if entry is None:
                continue
            raw, flags = entry
            if headers_only:
                raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
            flag_text = " ".join(flags)
            head = f"1 (UID {uid} FLAGS ({flag_text}) BODY[] {{{len(raw)}}}".encode()
            found.append(MailMessage([(head, raw), b")"]))
        return found
