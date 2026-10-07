"""The messages of the selected folder: searched, fetched, flagged, moved,
stored and deleted. Nothing here sets ``\\Seen`` by reading."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ....common.chunks import batched
from ....common.clock import utc_now
from ....errors import BadRequestError, NotSupportedError, ProviderError
from ..transport import text
from .responses import (
    capabilities,
    flags,
    message_id,
    new_uids,
    part,
    translated,
    with_code,
)
from .values import MAX_HEADER_BYTES, FetchedMessage, SearchCriteria

if TYPE_CHECKING:
    from .session import ImapSession

_HEADER = f"BODY.PEEK[HEADER]<0.{MAX_HEADER_BYTES}>"
_MESSAGE_ID = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
# Control characters, not allowed in a search text.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# UIDs per FETCH ... (CHANGEDSINCE n). A command line of a few kilobytes
# stays within what servers accept.
_CHANGED_BATCH = 500


class Messages:
    def __init__(self, session: ImapSession, max_bytes: int) -> None:
        self._session = session
        self._max_bytes = max_bytes

    # --- finding --------------------------------------------------------------------

    def search(self, criteria: SearchCriteria) -> list[int]:
        """UIDs in the selected folder, ascending."""
        query = _query(criteria)
        if query is None:
            return []
        texts = (criteria.text, criteria.sender, criteria.to, criteria.subject)
        wide = any(v and not v.isascii() for v in texts)
        with translated():
            found = self._session.client().search(
                query or "ALL", "UTF-8" if wide else None
            )
        return sorted(int(u) for u in found)

    def search_message_id(self, header: str) -> list[int]:
        """UIDs in the selected folder with this ``Message-ID``."""
        with translated():
            found = self._session.client().search(["HEADER", "Message-ID", header])
        return sorted(int(u) for u in found)

    def changed_since(self, uids: list[int], modseq: int) -> list[int]:
        """Those of ``uids`` in the selected folder whose flags changed after
        ``modseq`` (CONDSTORE, RFC 7162). Reads flags only, in batches, so
        a command line stays short."""
        changed: list[int] = []
        with translated():
            client = self._session.client()
            for batch in batched(uids, _CHANGED_BATCH):
                found = client.fetch(
                    batch, ["FLAGS"], modifiers=[f"CHANGEDSINCE {modseq}"]
                )
                changed += [int(uid) for uid in found]
        return sorted(changed)

    # --- fetching -------------------------------------------------------------------

    def fetch_headers(self, uids: list[int]) -> list[FetchedMessage]:
        """Flags and headers. Never sets ``\\Seen``."""
        return [
            FetchedMessage(uid, flags(data), part(data, b"BODY[HEADER]"))
            for uid, data in self._fetch(uids, ["FLAGS", _HEADER]).items()
        ]

    def fetch_message(self, uid: int) -> FetchedMessage | None:
        found = self._fetch([uid], ["FLAGS", self._whole()]).get(uid)
        if found is None:
            return None
        return FetchedMessage(uid, flags(found), self._body(uid, found))

    def fetch_raw(self, uid: int) -> bytes | None:
        found = self._fetch([uid], [self._whole()]).get(uid)
        return self._body(uid, found) if found is not None else None

    def fetch_message_ids(self, uids: list[int]) -> dict[int, str | None]:
        """The ``Message-ID`` header of each UID in the selected folder. Reads
        only that header and never sets ``\\Seen``."""
        return {
            uid: message_id(part(data, b"BODY[HEADER.FIELDS"))
            for uid, data in self._fetch(uids, [_MESSAGE_ID]).items()
        }

    def _whole(self) -> str:
        """One byte more than allowed, so a message too large shows."""
        return f"BODY.PEEK[]<0.{self._max_bytes + 1}>"

    def _body(self, uid: int, data: dict[bytes, Any]) -> bytes:
        body = part(data, b"BODY[]")
        if len(body) > self._max_bytes:
            raise ProviderError(f"message {uid} is larger than {self._max_bytes} bytes")
        return body

    def _fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, Any]]:
        if not uids:
            return {}
        with translated():
            found = self._session.client().fetch(uids, items)
        return {int(uid): data for uid, data in found.items()}

    # --- changing -------------------------------------------------------------------

    def store_flags(self, uids: list[int], add: list[str], remove: list[str]) -> None:
        """Set and clear the same flags on messages of the selected folder."""
        with translated():
            client = self._session.client()
            if add:
                client.add_flags(uids, add, silent=True)
            if remove:
                client.remove_flags(uids, remove, silent=True)

    def move(self, uids: list[int], target: str) -> dict[int, int]:
        """Move messages of the selected folder into ``target`` with one
        command. Returns their UIDs there, as far as the server reports them
        (``COPYUID``, RFC 4315). Needs ``MOVE``, or ``UIDPLUS`` to copy and
        expunge just these."""
        with translated():
            client = self._session.client()
            announced = capabilities(client)
            if "MOVE" in announced:
                reported = with_code(
                    client, "COPYUID", lambda: client.move(uids, target)
                )
            elif "UIDPLUS" in announced:

                def copy_and_expunge() -> Any:
                    answer = client.copy(uids, target)
                    client.add_flags(uids, ["\\Deleted"], silent=True)
                    client.uid_expunge(uids)
                    return answer

                reported = with_code(client, "COPYUID", copy_and_expunge)
            else:
                raise NotSupportedError(
                    "the mail server offers neither MOVE nor UIDPLUS: moving "
                    "would expunge other deleted messages of the folder too"
                )
        return new_uids(reported)

    def expunge(self, uids: list[int]) -> None:
        """Delete messages of the selected folder for good. Needs
        ``UIDPLUS``: a plain EXPUNGE would take every message marked
        deleted with it, other clients' too."""
        with translated():
            client = self._session.client()
            if "UIDPLUS" not in capabilities(client):
                raise NotSupportedError(
                    "the mail server offers no UIDPLUS: deleting one message "
                    "for good would expunge other deleted messages too"
                )
            client.add_flags(uids, ["\\Deleted"], silent=True)
            client.uid_expunge(uids)

    def append(self, folder: str, raw: bytes, flags: list[str]) -> int | None:
        """Store a message in ``folder``. Returns its UID where the server
        reports it (``APPENDUID``, RFC 4315)."""
        with translated():
            client = self._session.client()
            reported = with_code(
                client,
                "APPENDUID",
                lambda: client.append(folder, raw, flags=flags, msg_time=utc_now()),
            )
        for item in reported:
            match = re.search(r"(?:APPENDUID )?\d+ (\d+)", text(item) if item else "")
            if match:
                return int(match.group(1))
        return None


def _query(criteria: SearchCriteria) -> list[Any] | None:
    """The SEARCH keys of ``criteria``, None when nothing can match."""
    query = _text_keys(criteria)
    if criteria.since is not None:
        query += ["SINCE", criteria.since]
    if criteria.before is not None:
        query += ["BEFORE", criteria.before]
    if criteria.unread is not None:
        query.append("UNSEEN" if criteria.unread else "SEEN")
    if criteria.flagged is not None:
        query.append("FLAGGED" if criteria.flagged else "UNFLAGGED")
    if criteria.mixed is not None:
        mixed = ["HEADER", "Content-Type", "multipart/mixed"]
        query += mixed if criteria.mixed else ["NOT", *mixed]
    if criteria.before_uid is not None:
        # The server leaves out what an earlier page delivered.
        if criteria.before_uid <= 1:
            return None
        query += ["UID", f"1:{criteria.before_uid - 1}"]
    return query


def _text_keys(criteria: SearchCriteria) -> list[Any]:
    texts = {
        "TEXT": criteria.text,
        "FROM": criteria.sender,
        "TO": criteria.to,
        "SUBJECT": criteria.subject,
    }
    query: list[Any] = []
    for key, value in texts.items():
        if value:
            if _CONTROL.search(value):
                # The library quotes but keeps line breaks: they would end
                # the command and start one of the caller's choosing.
                raise BadRequestError("search text must not hold control characters")
            query += [key, value]
    return query
