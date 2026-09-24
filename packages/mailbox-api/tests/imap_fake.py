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
        self._box.calls.append(("status", name, tuple(options)))
        folder = self._box.folders[name]
        values = {
            "UIDVALIDITY": folder.uidvalidity,
            "UIDNEXT": max(folder.messages, default=0) + 1,
            "MESSAGES": len(folder.messages),
        }
        return {k: v for k, v in values.items() if k in options}


class _Client:
    capabilities = ("IMAP4REV1", "ID")

    def __init__(self, box: FakeMailBox) -> None:
        self._box = box

    def xatom(self, name: str, arguments: str) -> tuple[str, list[bytes]]:
        self._box.calls.append(("xatom", name, arguments))
        return ("OK", [b""])

    def capability(self) -> tuple[str, list[bytes]]:
        return ("OK", [" ".join(self._box.capabilities).encode()])

    def uid(self, command: str, uid: str, parts: str) -> tuple[str, list[Any]]:
        self._box.calls.append(("uid", command, uid, parts))
        assert "PEEK" in parts, "a read must never set \\Seen"
        folder = self._box.folders[self._box.selected]
        if "HEADER.FIELDS (MESSAGE-ID)" in parts:
            return ("OK", self._message_ids(folder, uid))
        entry = folder.messages.get(int(uid))
        if entry is None:
            return ("OK", [None])
        return (
            "OK",
            [(f"1 (UID {uid} BODY[] {{{len(entry[0])}}}".encode(), entry[0]), b")"],
        )

    def _message_ids(self, folder: FakeFolder, uids: str) -> list[Any]:
        """Like imaplib hands them out: a (head, literal) tuple and a closing
        part per message. ``uid_last`` puts the UID after the literal, as
        some servers do."""
        data: list[Any] = []
        for number, uid in enumerate(int(u) for u in uids.split(",")):
            entry = folder.messages.get(uid)
            if entry is None:
                continue
            head, _, _ = entry[0].partition(b"\n\n")
            block = b""
            inside = False
            for line in head.split(b"\n"):
                # A header, with the lines folded into it.
                if not line[:1].isspace():
                    inside = line.lower().startswith(b"message-id:")
                if inside:
                    block += line + b"\r\n"
            block += b"\r\n"
            item = f"BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(block)}}}"
            if self._box.uid_last:
                data += [
                    (f"{number + 1} ({item}".encode(), block),
                    f" UID {uid})".encode(),
                ]
            else:
                data += [(f"{number + 1} (UID {uid} {item}".encode(), block), b")"]
        return data


class _Idle:
    """IDLE answers from a script: one list of lines per poll."""

    def __init__(self, box: FakeMailBox) -> None:
        self._box = box

    def start(self) -> None:
        self._box.calls.append(("idle", self._box.selected))

    def poll(self, timeout: float) -> list[bytes]:
        if self._box.idle_script:
            return self._box.idle_script.pop(0)
        return []

    def stop(self) -> None:
        self._box.calls.append(("done",))


class FakeMailBox:
    """Shared across sessions of one test, like a server."""

    def __init__(self, password: str = "secret") -> None:
        self.password = password
        self.delimiter = "/"
        self.folders: dict[str, FakeFolder] = {"INBOX": FakeFolder()}
        self.selected = "INBOX"
        self.calls: list[tuple[Any, ...]] = []
        self.logins = 0
        self.failures: list[Exception] = []
        self.folder = _FolderManager(self)
        self.client = _Client(self)
        self.idle = _Idle(self)
        self.idle_script: list[list[bytes]] = []
        self.capabilities = ["IMAP4REV1", "IDLE", "UIDPLUS"]
        self.uid_last = False
        self.error = RuntimeError

    def move(self, source: str, uid: int, target: str, new_uid: int) -> None:
        """Another client moves a message."""
        entry = self.folders[source].messages.pop(uid)
        self.folders.setdefault(target, FakeFolder()).messages[new_uid] = entry

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
        if self.failures:
            raise self.failures.pop(0)
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
