"""What the sync worker asks of the mailbox, each a sequence under the
lock: the state of each folder, its contents, the Message-ID headers,
and with CONDSTORE which flags changed."""

from __future__ import annotations

from ...protocols import SearchCriteria
from . import mappers
from .mailbox import Mailbox
from .messages import by_folder


def folder_states(box: Mailbox) -> dict[str, str]:
    """``UIDVALIDITY.UIDNEXT.MESSAGES``, with CONDSTORE also
    ``.HIGHESTMODSEQ``, so that a flag change changes the state too."""
    modseq = "CONDSTORE" in box.session.server_capabilities()
    box.session.noop()
    states = {}
    for folder in box.list_folders():
        validity, uidnext, count, highest = box.session.folder_state(
            mappers.folder_name(folder.id), modseq=modseq
        )
        state = f"{validity}.{uidnext}.{count}"
        states[folder.id] = state if highest is None else f"{state}.{highest}"
    return states


def flag_changes(
    box: Mailbox, folder_id: str, since: str, message_ids: list[str]
) -> list[str]:
    """Only with CONDSTORE, and only while the folder keeps its UIDs."""
    parts = since.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return []
    folder = mappers.folder_name(folder_id)
    validity = int(parts[0])
    by_uid = by_folder(message_ids)[0].get((folder, validity), {})
    if not by_uid or box.session.select(folder) != validity:
        return []
    changed = box.session.changed_since(sorted(by_uid), int(parts[3]))
    return [by_uid[uid] for uid in changed if uid in by_uid]


def folder_contents(box: Mailbox, folder_id: str) -> list[str]:
    folder = mappers.folder_name(folder_id)
    validity = box.session.select(folder)
    return [
        mappers.message_id(folder, validity, uid)
        for uid in box.session.search(SearchCriteria())
    ]


def message_headers(
    box: Mailbox, folder: str, validity: int, uids: list[int]
) -> dict[str, str | None]:
    if box.session.select(folder) != validity:
        return {}  # renumbered: these ids are gone
    return {
        mappers.message_id(folder, validity, uid): header
        for uid, header in box.session.fetch_message_ids(uids).items()
    }
