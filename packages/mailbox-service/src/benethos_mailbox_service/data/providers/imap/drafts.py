"""Drafts in the folder with the drafts role, each a sequence under the
lock. A draft id names a message in that folder, any other id is not
found."""

from __future__ import annotations

from ....errors import NotFoundError, ProviderError, missing
from ...models import FolderRole, MessageSummary, Page
from . import mappers
from .mailbox import Mailbox
from .messages import append, get_raw, list_messages, open_writable


def list_drafts(box: Mailbox, limit: int, cursor: str | None) -> Page[MessageSummary]:
    drafts = mappers.folder_id(_drafts_folder(box))
    return list_messages(box, drafts, limit, cursor)


def save_draft(
    box: Mailbox, raw: bytes, replaces: str | None, *, retried: bool = False
) -> MessageSummary:
    drafts = _drafts_folder(box)
    # Checked before the new one is stored: a wrong id changes nothing.
    old = _draft_place(replaces, drafts) if replaces else None
    if old is not None and not retried:
        # A retried step may have removed it already, after it stored
        # the new one, which append then finds by its Message-ID.
        validity, uid = old
        found, _ = open_writable(box, drafts, validity, [uid])
        if uid not in found:
            raise missing("draft", replaces)
    saved = append(box, drafts, raw, ["\\Draft", "\\Seen"])
    if saved is None:
        raise ProviderError("the draft was stored but cannot be found again")
    if old is not None:
        try:
            _delete_draft_at(box, drafts, *old)
        except NotFoundError:
            pass  # gone already: a retried step removed it before the drop
    return saved


def get_draft(box: Mailbox, draft_id: str) -> bytes:
    _draft_place(draft_id, _drafts_folder(box))
    return get_raw(box, draft_id)


def delete_draft(box: Mailbox, draft_id: str) -> None:
    drafts = _drafts_folder(box)
    _delete_draft_at(box, drafts, *_draft_place(draft_id, drafts))


def _delete_draft_at(box: Mailbox, drafts: str, validity: int, uid: int) -> None:
    found, _ = open_writable(box, drafts, validity, [uid])
    if uid not in found:
        raise missing("draft")
    box.session.expunge([uid])


def _drafts_folder(box: Mailbox) -> str:
    return box.required_folder(FolderRole.DRAFTS)


def _draft_place(draft_id: str, drafts: str) -> tuple[int, int]:
    """UIDVALIDITY and UID of a draft id. Not found unless it names a
    message in the drafts folder."""
    absent = missing("draft", draft_id)
    try:
        folder, validity, uid = mappers.parse_message_id(draft_id)
    except NotFoundError:
        raise absent from None
    if folder != drafts:
        raise absent
    return validity, uid
