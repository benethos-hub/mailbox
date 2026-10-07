"""The folders of the fake IMAP server: one folder's state, and the folder
commands of ``imapclient.IMAPClient`` that ``imap_fake.FakeMailBox`` answers.
"""

from __future__ import annotations

import imaplib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass
class FakeFolder:
    flags: tuple[str, ...] = ()
    uidvalidity: int = 1
    messages: dict[int, tuple[bytes, tuple[str, ...]]] = field(default_factory=dict)
    # Like a real server, UIDNEXT never goes down, even when messages leave.
    highest_uid: int = 0
    # CONDSTORE: the modification sequence of each message's last change,
    # and the highest of the folder, which never goes down either.
    modseqs: dict[int, int] = field(default_factory=dict)
    highest_modseq: int = 0

    @property
    def uidnext(self) -> int:
        self.highest_uid = max(self.highest_uid, *self.messages, 0)
        return self.highest_uid + 1


class FolderCommands:
    """LIST, LSUB, NAMESPACE, CREATE, RENAME, DELETE, SUBSCRIBE, SELECT and
    STATUS. ``FakeMailBox`` sets the state they work on."""

    calls: list[tuple[Any, ...]]
    folders: dict[str, FakeFolder]
    delimiter: str
    selected: str
    subscribed: set[str]
    namespace_prefix: str
    permanent_flags: list[str]
    writable: bool
    announced: list[str]

    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes, str]]:
        return [
            (tuple(f.encode() for f in folder.flags), self.delimiter.encode(), name)
            for name, folder in self.folders.items()
        ]

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

    def folder_status(self, name: str, what: list[str]) -> dict[bytes, int]:
        self.calls.append(("status", name, tuple(what)))
        folder = self.folders[name]
        values = {
            "UIDVALIDITY": folder.uidvalidity,
            "UIDNEXT": folder.uidnext,
            "MESSAGES": len(folder.messages),
        }
        if "CONDSTORE" in self.announced:
            values["HIGHESTMODSEQ"] = folder.highest_modseq
        return {k.encode(): v for k, v in values.items() if k in what}
