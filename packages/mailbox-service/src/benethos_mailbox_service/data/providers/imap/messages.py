"""Messages listed, read, stored and changed, each a sequence under the
lock. A change works one folder at a time: one SELECT, one STORE per set
of flag changes, one MOVE."""

from __future__ import annotations

from typing import Any

from ....errors import (
    BadRequestError,
    MailboxServiceError,
    NotFoundError,
    missing,
    missing_message,
)
from ...mail import convert, parse
from ...models import (
    AttachmentContent,
    FolderRole,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
)
from ...protocols import SearchCriteria
from .. import rules
from . import mappers
from .mailbox import Mailbox, names

# --- listing and reading ----------------------------------------------------------


def list_messages(
    box: Mailbox,
    folder_id: str | None,
    limit: int,
    cursor: str | None,
    search: MessageFilter | None = None,
) -> Page[MessageSummary]:
    folder = mappers.folder_name(folder_id) if folder_id else mappers.INBOX
    before: int | None = None
    expected_validity: int | None = None
    if cursor:
        cursor_folder, expected_validity, before = mappers.parse_cursor(cursor)
        if cursor_folder != folder:
            raise rules.invalid_cursor()
    validity = box.session.select(folder)
    if expected_validity is not None and expected_validity != validity:
        raise BadRequestError("the folder changed on the server: start again")
    uids = box.session.messages.search(_criteria(search or MessageFilter(), before))
    page = list(reversed(uids[-limit:]))
    messages = {
        int(m.uid): m for m in box.session.messages.fetch_headers(page) if m.uid
    }
    items = [
        mappers.summary(messages[uid], folder, validity)
        for uid in page
        if uid in messages
    ]
    more = len(uids) > limit
    return Page[MessageSummary](
        items=items,
        next_cursor=mappers.cursor(folder, validity, page[-1]) if more else None,
    )


def select_message(box: Mailbox, message_id: str) -> tuple[str, int, int]:
    """Select the message's folder: its folder, UIDVALIDITY and UID."""
    folder, validity, uid = mappers.parse_message_id(message_id)
    if box.session.select(folder) != validity:
        raise missing_message(message_id)
    return folder, validity, uid


def _fetch(box: Mailbox, message_id: str) -> tuple[Any, str, int]:
    folder, validity, uid = select_message(box, message_id)
    message = box.session.messages.fetch_message(uid)
    if message is None:
        raise missing_message(message_id)
    return message, folder, validity


def get_message(box: Mailbox, message_id: str) -> Message:
    message, folder, validity = _fetch(box, message_id)
    return mappers.message(message, folder, validity)


def get_attachment(
    box: Mailbox, message_id: str, attachment_id: str
) -> AttachmentContent:
    message, _, _ = _fetch(box, message_id)
    return convert.attachment(message, attachment_id)


def get_raw(box: Mailbox, message_id: str) -> bytes:
    _, _, uid = select_message(box, message_id)
    raw = box.session.messages.fetch_raw(uid)
    if raw is None:
        raise missing_message(message_id)
    return raw


# --- storing ----------------------------------------------------------------------


def store_sent(box: Mailbox, raw: bytes) -> MessageSummary | None:
    """A read copy in the folder with the sent role, as mail clients do.
    None where the account has no such folder."""
    sent = box.role_folder(FolderRole.SENT)
    if sent is None:
        return None
    return append(box, sent, raw, ["\\Seen"])


def append(
    box: Mailbox, folder: str, raw: bytes, flags: list[str]
) -> MessageSummary | None:
    """Store ``raw`` in ``folder``. The stored message, found by its UID
    from APPENDUID or else by its Message-ID. None if neither finds it.

    A message with this Message-ID that the folder holds already is
    that stored message: the guard retries a step whose connection
    dropped, and the APPEND may have gone through before the drop."""
    header = parse.ParsedMessage(raw).message_id
    validity = box.session.select(folder)
    stored = box.session.messages.search_message_id(header) if header else []
    uid = stored[-1] if stored else box.session.messages.append(folder, raw, flags)
    if uid is None:
        validity = box.session.select(folder)
        matches = box.session.messages.search_message_id(header) if header else []
        uid = matches[-1] if matches else None
    found = box.session.messages.fetch_headers([uid]) if uid else []
    return mappers.summary(found[0], folder, validity) if found else None


# --- changing, one folder at a time -----------------------------------------------


def update_in_folder(
    box: Mailbox, folder: str, validity: int, uids: list[int], changes: MessageUpdate
) -> dict[int, MessageSummary | MailboxServiceError]:
    """One folder's share of an update: one SELECT, one STORE per set
    of flag changes, one MOVE."""
    found, permanent = open_writable(box, folder, validity, uids)
    results = _missing(uids, found)
    if not found:
        return results
    target = _move_target(box, changes, folder)
    plans: dict[tuple[tuple[str, ...], tuple[str, ...]], list[int]] = {}
    for uid, message in found.items():
        add, remove = mappers.flag_changes(message.flags, changes, permanent)
        if add or remove:
            plans.setdefault((tuple(add), tuple(remove)), []).append(uid)
    for (to_add, to_remove), plan_uids in plans.items():
        box.session.messages.store_flags(plan_uids, list(to_add), list(to_remove))
    if plans:
        stored = list(found)
        found = {int(m.uid): m for m in box.session.messages.fetch_headers(stored)}
        # Expunged by another client between the two fetches.
        results.update(_missing(stored, found))
    if target is None:
        results.update(
            {uid: mappers.summary(m, folder, validity) for uid, m in found.items()}
        )
        return results
    moved = _move(box, found, target)
    for uid, message in found.items():
        # Not found in the target at once: the next sync follows it.
        results[uid] = moved.get(uid) or mappers.summary(
            message, folder, validity
        ).model_copy(update={"folder_ids": [mappers.folder_id(target)]})
    return results


def delete_in_folder(
    box: Mailbox,
    folder: str,
    validity: int,
    uids: list[int],
    permanent: bool,
    retried: bool = False,
) -> dict[int, MessageSummary | None | MailboxServiceError]:
    found, _ = open_writable(box, folder, validity, uids)
    results: dict[int, MessageSummary | None | MailboxServiceError] = dict(
        _missing(uids, found)
    )
    if retried:
        # Gone from the folder: the first try deleted or moved them,
        # to a place this try cannot name.
        results = {uid: None for uid in results}
    if not found:
        return results
    if permanent:
        box.session.messages.expunge(list(found))
        results.update({uid: None for uid in found})
        return results
    trash = box.required_folder(FolderRole.TRASH)
    if trash == folder:
        raise rules.in_trash_already()
    moved = _move(box, found, trash)
    results.update({uid: moved.get(uid) for uid in found})
    return results


def open_writable(
    box: Mailbox, folder: str, validity: int, uids: list[int]
) -> tuple[dict[int, Any], frozenset[str]]:
    """Select a folder read-write and fetch the headers of ``uids``.
    None found when the folder was renumbered."""
    current, permanent = box.session.select_writable(folder)
    if current != validity:
        return {}, permanent
    found = {int(m.uid): m for m in box.session.messages.fetch_headers(uids)}
    return found, permanent


def _move(
    box: Mailbox, found: dict[int, Any], target: str
) -> dict[int, MessageSummary]:
    """Move messages of the selected folder with one command. Their
    summaries in ``target``, for those found there at once."""
    new_uids = box.session.messages.move(list(found), target)
    target_validity = box.session.select(target)
    for uid, message in found.items():
        header = message.message_id
        if uid not in new_uids and header and _searchable(header):
            # No COPYUID: find it by its Message-ID, if that is unambiguous.
            matches = box.session.messages.search_message_id(header)
            if len(matches) == 1:
                new_uids[uid] = matches[0]
    fetched = {
        int(m.uid): m
        for m in box.session.messages.fetch_headers(list(new_uids.values()))
    }
    return {
        uid: mappers.summary(fetched[new], target, target_validity)
        for uid, new in new_uids.items()
        if new in fetched
    }


def _move_target(box: Mailbox, changes: MessageUpdate, current: str) -> str | None:
    """The folder to move to, or None to stay."""
    wanted = rules.move_target(changes, box.capabilities)
    if wanted is None:
        return None
    target = mappers.folder_name(wanted)
    if target == current:
        return None
    if target not in names(box.session.folders.list_folders()):
        raise missing("folder", wanted)
    return target


# --- ids --------------------------------------------------------------------------


def by_folder(
    message_ids: list[str],
) -> tuple[dict[tuple[str, int], dict[int, str]], dict[str, NotFoundError]]:
    """The ids by folder and UIDVALIDITY, as UID -> id, and those that are
    no id of this adapter."""
    folders: dict[tuple[str, int], dict[int, str]] = {}
    unknown: dict[str, NotFoundError] = {}
    for message_id in message_ids:
        try:
            folder, validity, uid = mappers.parse_message_id(message_id)
        except NotFoundError as exc:
            unknown[message_id] = exc
            continue
        folders.setdefault((folder, validity), {})[uid] = message_id
    return folders, unknown


def _missing(
    uids: list[int], found: dict[int, Any]
) -> dict[int, MessageSummary | MailboxServiceError]:
    """``NotFoundError`` for every UID the folder no longer holds."""
    return {uid: missing_message() for uid in uids if uid not in found}


def _criteria(search: MessageFilter, before_uid: int | None) -> SearchCriteria:
    """The API's filter as IMAP SEARCH keys."""
    return SearchCriteria(
        text=search.text,
        sender=search.sender,
        to=search.to,
        subject=search.subject,
        since=search.after,
        before=search.before,
        unread=search.unread,
        flagged=search.starred,
        mixed=search.has_attachments,
        before_uid=before_uid,
    )


def _searchable(header: str) -> bool:
    """Whether a SEARCH can carry the Message-ID: a sender may write any
    bytes there, and imaplib writes commands in printable ASCII. Without
    it the next sync follows the moved message."""
    return header.isascii() and header.isprintable()
