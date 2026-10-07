"""A plain IMAP connection, standing in for another mail client: what
a check sees of a mailbox without the service in between."""

from __future__ import annotations

import imaplib
import re
import ssl
from typing import Any


class OtherClient:
    """A plain imaplib connection, standing in for another mail client."""

    def __init__(self, env: dict[str, str], account: dict[str, str]) -> None:
        host = env["LIVE_IMAP_HOST"]
        port = int(env.get("LIVE_IMAP_PORT", "993"))
        context = ssl.create_default_context()
        if env.get("LIVE_IMAP_SECURITY", "tls") == "tls":
            self.conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                host, port, ssl_context=context
            )
        else:
            self.conn = imaplib.IMAP4(host, port)
            self.conn.starttls(ssl_context=context)
        self.conn.login(account["username"], account["password"])

    def folder_name(self, name: str) -> str:
        """``name`` inside the personal namespace, e.g. ``INBOX.name`` on
        servers that keep every folder below the inbox."""
        status, data = self.conn.namespace()
        match = re.match(rb'\(\("([^"]*)" (?:"([^"]*)"|NIL)\)', data[0] or b"")
        if status != "OK" or match is None:
            return name
        return match.group(1).decode() + name

    def create_folder(self, folder: str, subscribe: bool = False) -> None:
        """``subscribe`` makes mail clients such as Outlook show it: they list
        only subscribed folders."""
        status, data = self.conn.create(_quoted(folder))
        if status != "OK":
            raise RuntimeError(f"CREATE failed: {data!r}")
        if subscribe:
            self.conn.subscribe(_quoted(folder))

    def all_folders(self) -> set[str]:
        return self._names(self.conn.list())

    def subscribed_folders(self) -> set[str]:
        return self._names(self.conn.lsub())

    def _names(self, answer: tuple[str, list[Any]]) -> set[str]:
        status, data = answer
        names = set()
        for line in data if status == "OK" else []:
            if isinstance(line, bytes):
                match = re.match(rb'\([^)]*\) (?:"[^"]*"|NIL) (.+)$', line)
                if match:
                    names.add(match.group(1).decode().strip('"'))
        return names

    def sent_folder(self) -> str | None:
        return self._special_folder(b"\\sent")

    def trash_folder(self) -> str | None:
        return self._special_folder(b"\\trash")

    def drafts_folder(self) -> str | None:
        return self._special_folder(b"\\drafts")

    def _special_folder(self, flag: bytes) -> str | None:
        """The folder with this special-use flag (RFC 6154)."""
        status, data = self.conn.list()
        for line in data if status == "OK" else []:
            if not isinstance(line, bytes):
                continue
            match = re.match(rb'\(([^)]*)\) (?:"[^"]*"|NIL) (.+)$', line)
            if match and flag in match.group(1).lower():
                return match.group(2).decode().strip('"')
        return None

    def delete_folder(self, folder: str) -> bool:
        self.conn.unsubscribe(_quoted(folder))
        self.conn.select("INBOX")
        status, _ = self.conn.delete(_quoted(folder))
        return status == "OK"

    def flags(self, folder: str, subject: str) -> list[str]:
        """The flags of the one test mail, as the server keeps them."""
        found = self.uids(folder, subject)
        if len(found) != 1:
            return [f"({len(found)} mails)"]
        _, data = self.conn.uid("FETCH", found[0].decode(), "(FLAGS)")
        match = re.search(rb"FLAGS \(([^)]*)\)", data[0] if data and data[0] else b"")
        flags = match.group(1).decode().split() if match else []
        return sorted(f for f in flags if f != "\\Recent")

    def uids(self, folder: str, subject: str) -> list[bytes]:
        status, _ = self.conn.select(_quoted(folder))
        if status != "OK":
            return []
        _, data = self.conn.uid("SEARCH", "SUBJECT", _quoted(subject))
        return data[0].split() if data and data[0] else []

    def move(self, uid: bytes, target: str) -> None:
        status, data = self.conn.uid("MOVE", uid.decode(), _quoted(target))
        if status != "OK":
            raise RuntimeError(f"MOVE failed: {data!r}")

    def capabilities(self) -> set[str]:
        return {c.upper() for c in self.conn.capabilities}

    def set_flag(self, folder: str, subject: str, flag: str, on: bool) -> None:
        for uid in self.uids(folder, subject):
            sign = "+FLAGS.SILENT" if on else "-FLAGS.SILENT"
            self.conn.uid("STORE", uid.decode(), sign, f"({flag})")

    def delete_mail(self, folder: str, subject: str) -> int:
        found = self.uids(folder, subject)
        for uid in found:
            self.conn.uid("STORE", uid.decode(), "+FLAGS.SILENT", r"(\Deleted)")
        if found:
            self.conn.uid("EXPUNGE", b",".join(found).decode())
        return len(found)

    def close(self) -> None:
        try:
            self.conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
