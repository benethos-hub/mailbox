"""The messages of the in-memory mailbox: listed, searched, read, changed
and deleted."""

from __future__ import annotations

from ....errors import MailboxServiceError, missing
from ...models import (
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    received_or_written,
)
from .. import rules
from .store import Store, message, role_folder


def list_messages(
    store: Store,
    folder_id: str,
    limit: int,
    cursor: str | None,
    search: MessageFilter | None,
) -> Page[MessageSummary]:
    search = search or MessageFilter()
    found = [
        m
        for m in store.messages
        if _within(m, folder_id, store.folders) and _matches(m, search)
    ]
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        raise rules.invalid_cursor() from None
    chunk = found[start : start + limit]
    more = start + limit < len(found)
    return Page[MessageSummary](
        items=[_summary(m) for m in chunk],
        next_cursor=str(start + limit) if more else None,
    )


def get_attachment(
    store: Store, message_id: str, attachment_id: str
) -> AttachmentContent:
    for attachment in message(store, message_id).attachments:
        if attachment.id == attachment_id:
            data = store.attachment_data.get((message_id, attachment_id), b"")
            return AttachmentContent(
                filename=attachment.filename,
                content_type=attachment.content_type,
                data=data,
            )
    raise missing("attachment", attachment_id)


def get_raw(store: Store, message_id: str) -> bytes:
    found = message(store, message_id)
    if found.id in store.raws:
        return store.raws[found.id]
    body = found.text_body or ""
    return f"Subject: {found.subject or ''}\r\n\r\n{body}".encode()


async def update_messages(
    store: Store, message_ids: list[str], changes: MessageUpdate
) -> dict[str, MessageSummary | MailboxServiceError]:
    async def one(message_id: str) -> MessageSummary:
        found = message(store, message_id)
        fields = changes.model_dump(include={"unread", "starred"}, exclude_none=True)
        rules.move_target(changes, labels=store.labels)
        known = {f.id for f in store.folders}
        for folder_id in changes.named_folders():
            if folder_id not in known:
                raise missing("folder", folder_id)
        folders = changes.folders_after(found.folder_ids)
        if folders == []:
            raise rules.no_folder_left()
        if folders is not None:
            fields["folder_ids"] = folders
        keywords = changes.keywords_after(found.keywords)
        if keywords is not None:
            fields["keywords"] = sorted(keywords.values(), key=str.lower)
        updated = found.model_copy(update=fields)
        store.messages[store.messages.index(found)] = updated
        return _summary(updated)

    return await rules.per_id(message_ids, one)


async def delete_messages(
    store: Store, message_ids: list[str], permanent: bool
) -> dict[str, MessageSummary | None | MailboxServiceError]:
    async def one(message_id: str) -> MessageSummary | None:
        found = message(store, message_id)
        if permanent:
            store.messages.remove(found)
            return None
        trash = role_folder(store, FolderRole.TRASH)
        if trash in found.folder_ids:
            raise rules.in_trash_already()
        moved = found.model_copy(update={"folder_ids": [trash]})
        store.messages[store.messages.index(found)] = moved
        return _summary(moved)

    return await rules.per_id(message_ids, one)


def _summary(found: Message) -> MessageSummary:
    return MessageSummary.model_validate(found.model_dump())


def _within(found: Message, folder_id: str, folders: list[Folder]) -> bool:
    """Whether the message is in the folder. The folder with the role
    ``all`` holds every message but those in the trash and junk."""
    roles = {f.id: f.role for f in folders}
    if roles.get(folder_id) is not FolderRole.ALL:
        return folder_id in found.folder_ids
    outside = (FolderRole.TRASH, FolderRole.JUNK)
    return not any(roles.get(f) in outside for f in found.folder_ids)


def _matches(found: Message, search: MessageFilter) -> bool:
    """Case-insensitive substrings, as IMAP SEARCH compares."""

    def has(value: str | None, *fields: str | None) -> bool:
        return value is None or any(value.lower() in (f or "").lower() for f in fields)

    sender = found.sender
    when = received_or_written(found)
    day = when.date() if when else None
    return (
        has(search.text, found.subject, found.text_body)
        and has(
            search.sender,
            sender.email if sender else None,
            sender.name if sender else None,
        )
        and has(search.to, *(a.email for a in found.to))
        and has(search.subject, found.subject)
        and (search.after is None or (day is not None and day >= search.after))
        and (search.before is None or (day is not None and day < search.before))
        and search.flags_match(found)
    )
