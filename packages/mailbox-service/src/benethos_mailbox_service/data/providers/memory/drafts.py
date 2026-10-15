"""Drafts of the in-memory mailbox, and sending: what was sent is kept in
``outbox``, its copy in the sent folder."""

from __future__ import annotations

from ....errors import missing
from ...mail import convert, parse
from ...models import FolderRole, Message, MessageSummary, Page, SentMessage
from . import messages
from .store import Store, role_folder


def send(store: Store, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
    store.outbox.append((sender, list(recipients), raw))
    sent = next((f.id for f in store.folders if f.role is FolderRole.SENT), None)
    if sent is None:
        return SentMessage()
    parsed = parse.ParsedMessage(raw)
    copy = Message(
        id=f"sent_{len(store.outbox)}",
        folder_ids=[sent],
        subject=parsed.subject,
        message_id_header=parsed.message_id,
    )
    store.messages.append(copy)
    return SentMessage(sent_copy=MessageSummary.model_validate(copy.model_dump()))


def list_drafts(store: Store, limit: int, cursor: str | None) -> Page[MessageSummary]:
    drafts = role_folder(store, FolderRole.DRAFTS)
    return messages.list_messages(store, drafts, limit, cursor, None)


def save_draft(store: Store, raw: bytes, replaces: str | None) -> MessageSummary:
    drafts = role_folder(store, FolderRole.DRAFTS)
    old = _draft(store, replaces) if replaces else None
    parsed = parse.ParsedMessage(raw)
    store.drafts_saved += 1
    draft = Message.model_validate(
        {
            **convert.summary_fields(parsed),
            **convert.message_fields(parsed),
            # Stable ids: a replaced draft keeps its id.
            "id": old.id if old else f"draft_{store.drafts_saved}",
            "folder_ids": [drafts],
            "keywords": ["$draft"],
        }
    )
    if old is not None:
        store.messages.remove(old)
    store.messages.append(draft)
    store.raws[draft.id] = raw
    return MessageSummary.model_validate(draft.model_dump())


def get_draft(store: Store, draft_id: str) -> bytes:
    return store.raws[_draft(store, draft_id).id]


def delete_draft(store: Store, draft_id: str) -> None:
    draft = _draft(store, draft_id)
    store.messages.remove(draft)
    store.raws.pop(draft.id, None)


def _draft(store: Store, draft_id: str) -> Message:
    drafts = role_folder(store, FolderRole.DRAFTS)
    for found in store.messages:
        if found.id == draft_id and drafts in found.folder_ids:
            return found
    raise missing("draft", draft_id)
