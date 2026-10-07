"""The folders of an IMAP session: listed, made, renamed and deleted with
their subscriptions, and their state without selecting them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..transport import text
from .responses import capabilities, quietly, translated
from .values import RawFolder

if TYPE_CHECKING:
    from .session import ImapSession


class Folders:
    def __init__(self, session: ImapSession) -> None:
        self._session = session
        # The personal namespace, asked once per connection: the client
        # it was asked on, and the answer.
        self._namespace: tuple[Any, tuple[str, str | None]] | None = None

    def list_folders(self, subscriptions: bool = False) -> list[RawFolder]:
        """Every folder. With ``subscriptions`` also whether each one is
        subscribed, which costs one more command (LSUB)."""
        with translated():
            client = self._session.client()
            subscribed = (
                {str(name) for _, _, name in client.list_sub_folders()}
                if subscriptions
                else None
            )
            return [
                RawFolder(
                    str(name),
                    text(delimiter) if delimiter else None,
                    tuple(text(flag) for flag in flags),
                    None if subscribed is None else str(name) in subscribed,
                )
                for flags, delimiter, name in client.list_folders()
            ]

    def folder_state(
        self, folder: str, modseq: bool = False
    ) -> tuple[int, int, int, int | None]:
        """UIDVALIDITY, UIDNEXT, MESSAGES and, with ``modseq``, HIGHESTMODSEQ
        of a folder, without selecting it. The first three change whenever a
        message arrives or leaves, HIGHESTMODSEQ also when flags change
        (CONDSTORE, RFC 7162). None where the server does not report it."""
        items = ["UIDVALIDITY", "UIDNEXT", "MESSAGES"]
        if modseq:
            items.append("HIGHESTMODSEQ")
        with translated():
            status = self._session.client().folder_status(folder, items)
        highest = status.get(b"HIGHESTMODSEQ")
        return (
            int(status[b"UIDVALIDITY"]),
            int(status.get(b"UIDNEXT", 0)),
            int(status.get(b"MESSAGES", 0)),
            int(highest) if highest is not None else None,
        )

    def personal_namespace(self) -> tuple[str, str | None]:
        """Where top-level folders of the user go (RFC 2342), e.g.
        ``("INBOX.", ".")`` on servers that keep all folders below the inbox,
        and its delimiter. Asked once per connection."""
        with translated():
            client = self._session.client()
            if self._namespace is not None and self._namespace[0] is client:
                return self._namespace[1]
            found: tuple[str, str | None] = ("", None)
            if "NAMESPACE" in capabilities(client):
                personal = client.namespace().personal
                if personal:
                    prefix, delimiter = personal[0]
                    found = (text(prefix), text(delimiter) if delimiter else None)
        self._namespace = (client, found)
        return found

    def create_folder(self, name: str) -> None:
        """Create and subscribe: mail clients such as Outlook list only
        subscribed folders."""
        with translated():
            client = self._session.client()
            client.create_folder(name)
            client.subscribe_folder(name)

    def rename_folder(self, old: str, new: str) -> None:
        """Rename, and move the subscription along."""
        with translated():
            client = self._session.client()
            client.rename_folder(old, new)
            client.subscribe_folder(new)
            quietly(lambda: client.unsubscribe_folder(old))

    def delete_folder(self, name: str) -> None:
        """Delete, and drop the subscription, which would otherwise stay."""
        with translated():
            client = self._session.client()
            quietly(lambda: client.unsubscribe_folder(name))
            client.delete_folder(name)
