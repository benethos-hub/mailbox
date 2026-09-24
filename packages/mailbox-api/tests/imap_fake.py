"""A stand-in for ``imapclient.IMAPClient``: the same calls, answered from
memory, in the shapes IMAPClient hands out.

Messages are real RFC 822 bytes, so the real parser reads them. Only the
network is missing.
"""

from __future__ import annotations

import imaplib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from types import SimpleNamespace
from typing import Any

from imapclient.exceptions import LoginError


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
    # Like a real server, UIDNEXT never goes down, even when messages leave.
    highest_uid: int = 0

    @property
    def uidnext(self) -> int:
        self.highest_uid = max(self.highest_uid, *self.messages, 0)
        return self.highest_uid + 1


class FakeMailBox:
    """One fake server, shared by every session of a test.

    ``calls`` records what the client asked, e.g. ``("select", "INBOX",
    True)`` or ``("fetch", ("3", "1"), "header")``.
    """

    def __init__(self, password: str = "secret") -> None:
        self.password = password
        self.delimiter = "/"
        self.folders: dict[str, FakeFolder] = {"INBOX": FakeFolder()}
        self.selected = "INBOX"
        self.calls: list[tuple[Any, ...]] = []
        self.logins = 0
        # Raised one by one by the next searches.
        self.failures: list[Exception] = []
        # IDLE answers, one list of parsed responses per idle_check.
        self.idle_script: list[list[tuple[Any, ...]]] = []
        self.announced = ["IMAP4REV1", "ID", "IDLE", "UIDPLUS", "MOVE"]
        # Folder names a mail client would show. Servers often leave the
        # inbox out: clients show it anyway.
        self.subscribed: set[str] = set()
        # The personal namespace (NAMESPACE), e.g. "INBOX." on some servers.
        self.namespace_prefix = ""
        # What SELECT reports as PERMANENTFLAGS. "\*": any keyword.
        self.permanent_flags = ["\\Answered", "\\Flagged", "\\Deleted", "\\Seen", "\\*"]
        self.writable = False
        # Whether MOVE and COPY report the new UID (UIDPLUS).
        self.copyuid = True
        self.append_failure: Exception | None = None
        # imaplib's store of response codes, which IMAPClient keeps in _imap.
        self._imap = SimpleNamespace(untagged_responses={})

    # the factory signature ImapSession expects
    def __call__(self, server: Any, timeout: float) -> FakeMailBox:
        self.calls.append(("connect", server.host, server.port, server.security))
        return self

    # --- test helpers ---------------------------------------------------------------

    def add(
        self, folder: str, uid: int, raw: bytes, flags: tuple[str, ...] = ()
    ) -> None:
        target = self.folders.setdefault(folder, FakeFolder())
        target.messages[uid] = (raw, flags)
        target.highest_uid = max(target.highest_uid, uid)

    def other_client_moves(
        self, source: str, uid: int, target: str, new_uid: int
    ) -> None:
        """Another client moves a message."""
        entry = self.folders[source].messages.pop(uid)
        self.add(target, new_uid, *entry)

    # --- IMAPClient ---------------------------------------------------------------

    def capabilities(self) -> tuple[bytes, ...]:
        return tuple(c.encode() for c in self.announced)

    def id_(self, parameters: dict[str, str]) -> dict[bytes, bytes]:
        self.calls.append(("id", parameters))
        return {}

    def login(self, username: str, password: str) -> bytes:
        self.calls.append(("login", username))
        if password != self.password:
            raise LoginError("b'[AUTHENTICATIONFAILED] Authentication failed.'")
        self.logins += 1
        return b"Logged in"

    def oauth2_login(self, username: str, token: str) -> bytes:
        self.calls.append(("xoauth2", username))
        if token != self.password:
            raise LoginError("b'invalid token'")
        self.logins += 1
        return b"Logged in"

    def logout(self) -> bytes:
        self.calls.append(("logout",))
        return b"Logging out"

    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes, str]]:
        return [
            (tuple(f.encode() for f in folder.flags), self.delimiter.encode(), name)
            for name, folder in self.folders.items()
        ]

    def append(
        self, folder: str, msg: bytes, flags: Any = (), msg_time: Any = None
    ) -> bytes:
        """Stores the message; reports APPENDUID like a server with UIDPLUS
        (``copyuid`` False: none), or fails with ``append_failure``."""
        self.calls.append(("append", folder, tuple(flags)))
        if self.append_failure is not None:
            raise self.append_failure
        uid = self.folders[folder].uidnext
        self.add(folder, uid, msg.replace(b"\r\n", b"\n"), tuple(flags))
        if not self.copyuid:
            return b"Append completed"
        return f"[APPENDUID {self.folders[folder].uidvalidity} {uid}] Done".encode()

    def namespace(self) -> SimpleNamespace:
        return SimpleNamespace(personal=((self.namespace_prefix, self.delimiter),))

    def folder_exists(self, name: str) -> bool:
        return name in self.folders

    def create_folder(self, name: str) -> bytes:
        self.calls.append(("create", name))
        if name in self.folders:
            raise imaplib.IMAP4.error("create failed: exists")
        self.folders[name] = FakeFolder()
        return b"Create completed"

    def rename_folder(self, old: str, new: str) -> bytes:
        """Renames the folder and every folder below it, like a server."""
        self.calls.append(("rename", old, new))
        for name in [
            n for n in self.folders if n == old or n.startswith(old + self.delimiter)
        ]:
            self.folders[new + name[len(old) :]] = self.folders.pop(name)
        return b"Rename completed"

    def delete_folder(self, name: str) -> bytes:
        self.calls.append(("delete", name))
        del self.folders[name]
        return b"Delete completed"

    def subscribe_folder(self, name: str) -> None:
        self.subscribed.add(name)

    def unsubscribe_folder(self, name: str) -> None:
        if name not in self.subscribed:
            raise imaplib.IMAP4.error("unsubscribe failed: not subscribed")
        self.subscribed.discard(name)

    def list_sub_folders(self) -> list[tuple[tuple[bytes, ...], bytes, str]]:
        self.calls.append(("lsub",))
        return [f for f in self.list_folders() if f[2] in self.subscribed]

    def select_folder(self, name: str, readonly: bool = False) -> dict[bytes, Any]:
        self.calls.append(("select", name, readonly))
        if name not in self.folders:
            raise imaplib.IMAP4.error("select failed: no such folder")
        self.selected = name
        folder = self.folders[name]
        answer: dict[bytes, Any] = {
            b"UIDVALIDITY": folder.uidvalidity,
            b"UIDNEXT": folder.uidnext,
            b"EXISTS": len(folder.messages),
            b"PERMANENTFLAGS": tuple(f.encode() for f in self.permanent_flags),
        }
        answer[b"READ-ONLY" if readonly else b"READ-WRITE"] = True
        self.writable = not readonly
        return answer

    def add_flags(
        self, uids: list[int], flags: list[str], silent: bool = False
    ) -> None:
        self._store("+", uids, flags)

    def remove_flags(
        self, uids: list[int], flags: list[str], silent: bool = False
    ) -> None:
        self._store("-", uids, flags)

    def move(self, uids: list[int], target: str) -> bytes:
        self.calls.append(("move", tuple(uids), target))
        return self._copy(uids, target, remove=True, report="untagged")

    def copy(self, uids: list[int], target: str) -> bytes:
        self.calls.append(("copy", tuple(uids), target))
        return self._copy(uids, target, remove=False, report="tagged")

    def uid_expunge(self, uids: list[int]) -> None:
        self.calls.append(("expunge", tuple(uids)))
        folder = self.folders[self.selected]
        for uid in uids:
            if "\\Deleted" in folder.messages.get(uid, (b"", ()))[1]:
                del folder.messages[uid]

    def _copy(self, uids: list[int], target: str, remove: bool, report: str) -> bytes:
        """Like a server with UIDPLUS: MOVE reports COPYUID in an untagged
        response, COPY in the tagged one. ``copyuid`` False reports none."""
        assert self.writable, "moving needs the folder selected read-write"
        source = self.folders[self.selected]
        new = []
        for uid in uids:
            new_uid = self.folders[target].uidnext
            raw, flags = source.messages[uid]
            self.add(target, new_uid, raw, flags)
            if remove:
                del source.messages[uid]
            new.append(new_uid)
        code = (
            f"{self.folders[target].uidvalidity} "
            f"{','.join(map(str, uids))} {','.join(map(str, new))}"
        ).encode()
        if not self.copyuid:
            return b"Done"
        if report == "untagged":
            self._imap.untagged_responses.setdefault("COPYUID", []).append(code)
            return b"Move completed"
        return b"[COPYUID " + code + b"] Copy completed"

    def _store(self, sign: str, uids: list[int], flags: list[str]) -> None:
        assert self.writable, "STORE needs the folder selected read-write"
        self.calls.append(("store", sign, tuple(uids), tuple(flags)))
        folder = self.folders[self.selected]
        for uid in uids:
            raw, current = folder.messages[uid]
            if sign == "+":
                changed = tuple(dict.fromkeys((*current, *flags)))
            else:
                gone = {f.lower() for f in flags}
                changed = tuple(f for f in current if f.lower() not in gone)
            folder.messages[uid] = (raw, changed)

    def folder_status(self, name: str, what: list[str]) -> dict[bytes, int]:
        self.calls.append(("status", name, tuple(what)))
        folder = self.folders[name]
        values = {
            "UIDVALIDITY": folder.uidvalidity,
            "UIDNEXT": folder.uidnext,
            "MESSAGES": len(folder.messages),
        }
        return {k.encode(): v for k, v in values.items() if k in what}

    def search(self, criteria: Any, charset: str | None = None) -> list[int]:
        if self.failures:
            raise self.failures.pop(0)
        words = [criteria] if isinstance(criteria, str) else list(criteria)
        self.calls.append(("search", tuple(words), charset))
        text = words[words.index("TEXT") + 1].lower() if "TEXT" in words else None
        header = words[words.index("HEADER") + 2] if "HEADER" in words else None
        found = []
        for uid, (raw, flags) in self.folders[self.selected].messages.items():
            if header and header.encode() not in _message_id_block(raw):
                continue
            if "UNSEEN" in words and "\\Seen" in flags:
                continue
            if "SEEN" in words and "\\Seen" not in flags:
                continue
            if text and text not in raw.decode(errors="replace").lower():
                continue
            found.append(uid)
        return found

    def fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, Any]]:
        for item in items:
            assert "BODY" not in item or "PEEK" in item, "a read must never set \\Seen"
        kind = (
            "message-id"
            if any("MESSAGE-ID" in i for i in items)
            else "header"
            if "BODY.PEEK[HEADER]" in items
            else "full"
        )
        self.calls.append(("fetch", tuple(str(u) for u in uids), kind))
        folder = self.folders[self.selected]
        found: dict[int, dict[bytes, Any]] = {}
        for number, uid in enumerate(int(u) for u in uids):
            entry = folder.messages.get(uid)
            if entry is None:
                continue
            raw, flags = entry
            head = raw.split(b"\n\n", 1)[0] + b"\n\n"
            data: dict[bytes, Any] = {b"SEQ": number + 1}
            if "FLAGS" in items:
                data[b"FLAGS"] = tuple(f.encode() for f in flags)
            if kind == "message-id":
                data[b"BODY[HEADER.FIELDS (MESSAGE-ID)]"] = _message_id_block(head)
            elif kind == "header":
                data[b"BODY[HEADER]"] = head
            else:
                data[b"BODY[]"] = raw
            found[uid] = data
        return found

    def idle(self) -> None:
        self.calls.append(("idle", self.selected))

    def idle_check(self, timeout: float | None = None) -> list[tuple[Any, ...]]:
        return self.idle_script.pop(0) if self.idle_script else []

    def idle_done(self) -> tuple[bytes, list[Any]]:
        self.calls.append(("done",))
        return (b"Idle completed", [])


def _message_id_block(head: bytes) -> bytes:
    """The Message-ID header with the lines folded into it, as a server
    answers ``BODY[HEADER.FIELDS (MESSAGE-ID)]``."""
    block = b""
    inside = False
    for line in head.split(b"\n"):
        if not line[:1].isspace():
            inside = line.lower().startswith(b"message-id:")
        if inside:
            block += line + b"\r\n"
    return block + b"\r\n"
