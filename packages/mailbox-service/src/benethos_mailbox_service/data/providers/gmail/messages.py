"""Messages listed, read, changed and deleted. A change is one ``modify``
of a message's labels: flags and folders at once."""

from __future__ import annotations

from ....errors import (
    BadRequestError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    missing_message,
)
from ...mail import convert, parse
from ...models import (
    AttachmentContent,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
)
from .. import rules
from ..base import Capability
from . import mappers, reading
from .api import GmailApi, id_
from .shapes import GmailMessage, Messages


async def list_messages(
    api: GmailApi,
    folder_id: str | None,
    limit: int,
    cursor: str | None,
    search: MessageFilter | None,
) -> Page[MessageSummary]:
    """Newest first. Without a folder: every message, the trash and the
    spam among them."""
    if folder_id is not None:
        await reading.require_folder(api, folder_id)
    scope = mappers.scope(folder_id, search)
    params = [("maxResults", str(limit)), *reading.folder_params(folder_id)]
    if cursor:
        params.append(("pageToken", mappers.page_token(cursor, scope)))
    query = mappers.query(search)
    if query:
        params.append(("q", query))
    page = await api.read(Messages, "GET", "/messages", params=params)
    ids = [m.id for m in page.messages]
    found = await reading.summaries(api, ids)
    token = page.next_page_token
    return Page[MessageSummary](
        items=[found[i] for i in ids if i in found],
        next_cursor=mappers.cursor(scope, token) if token else None,
    )


async def get_message(api: GmailApi, message_id: str) -> Message:
    found = await _with_source(api, message_id)
    known = await reading.known_folders(api)
    return mappers.message(found, reading.source(found), known)


async def get_raw(api: GmailApi, message_id: str) -> bytes:
    return reading.source(await _with_source(api, message_id))


async def get_attachment(
    api: GmailApi, message_id: str, attachment_id: str
) -> AttachmentContent:
    raw = await get_raw(api, message_id)
    return convert.attachment(parse.ParsedMessage(raw), attachment_id)


async def _with_source(api: GmailApi, message_id: str) -> GmailMessage:
    if not reading.is_id(message_id):
        raise missing_message(message_id)
    try:
        return await reading.with_source(api, message_id)
    except NotFoundError:
        raise missing_message(message_id) from None


# --- changing ---------------------------------------------------------------------


async def update_messages(
    api: GmailApi,
    capabilities: frozenset[Capability],
    message_ids: list[str],
    changes: MessageUpdate,
) -> dict[str, MessageSummary | MailboxServiceError]:
    failure: MailboxServiceError
    if changes.keywords:
        failure = NotSupportedError(
            "gmail keeps no keywords: its labels are the folders"
        )
        return dict.fromkeys(message_ids, failure)
    targets = None
    known: set[str] = set()
    if changes.folder_ids is not None:
        rules.move_target(changes, capabilities)
        targets = set(changes.folder_ids)
        known = await reading.known_folders(api)
        unknown = next(
            (t for t in sorted(targets) if t not in known | {mappers.ALL_MAIL}), None
        )
        if unknown is not None:
            return dict.fromkeys(
                message_ids, NotFoundError(f"folder {unknown} not found")
            )
        if targets & mappers.NOT_TARGETS:
            failure = BadRequestError("gmail puts messages in sent and drafts itself")
            return dict.fromkeys(message_ids, failure)

    async def one(message_id: str) -> MessageSummary:
        current = await _labels(api, message_id) if targets is not None else set()
        add, remove = _change(current, targets, known, changes)
        if add or remove:
            await _modify(api, message_id, add, remove)
        return await _summary(api, message_id)

    return await rules.per_id(message_ids, one)


def _change(
    current: set[str],
    targets: set[str] | None,
    known: set[str],
    changes: MessageUpdate,
) -> tuple[list[str], list[str]]:
    """The labels to add and to take off: the folders become exactly
    ``targets``, and the flags as asked."""
    add: set[str] = set()
    remove: set[str] = set()
    if targets is not None:
        folders = (known | mappers.OUTSIDE_ALL) - mappers.NOT_TARGETS
        wanted = targets - {mappers.ALL_MAIL}
        add |= wanted - current
        remove |= (current & folders) - wanted
    for flag, label in (
        (changes.unread, mappers.UNREAD),
        (changes.starred, mappers.STARRED),
    ):
        if flag is not None:
            (add if flag else remove).add(label)
    return sorted(add), sorted(remove)


async def _labels(api: GmailApi, message_id: str) -> set[str]:
    if not reading.is_id(message_id):
        raise missing_message(message_id)
    try:
        found = await reading.get(api, message_id, {"format": "minimal"})
    except NotFoundError:
        raise missing_message(message_id) from None
    return set(found.label_ids)


async def _modify(
    api: GmailApi, message_id: str, add: list[str], remove: list[str]
) -> None:
    if not reading.is_id(message_id):
        raise missing_message(message_id)
    try:
        await api.call(
            "POST",
            f"/messages/{id_(message_id)}/modify",
            json_body={"addLabelIds": add, "removeLabelIds": remove},
        )
    except NotFoundError:
        raise missing_message(message_id) from None


async def _summary(api: GmailApi, message_id: str) -> MessageSummary:
    found = await reading.summary(api, message_id)
    if found is None:
        raise missing_message(message_id)
    return found


async def delete_messages(
    api: GmailApi, message_ids: list[str], permanent: bool
) -> dict[str, MessageSummary | None | MailboxServiceError]:
    async def for_good(message_id: str) -> MessageSummary | None:
        if not reading.is_id(message_id):
            raise missing_message(message_id)
        try:
            await api.call("DELETE", f"/messages/{id_(message_id)}")
        except NotFoundError:
            raise missing_message(message_id) from None
        return None

    async def to_trash(message_id: str) -> MessageSummary | None:
        if mappers.TRASH in await _labels(api, message_id):
            raise rules.in_trash_already()
        try:
            await api.call("POST", f"/messages/{id_(message_id)}/trash")
        except NotFoundError:
            raise missing_message(message_id) from None
        return await reading.summary(api, message_id)

    one = for_good if permanent else to_trash
    return dict(await rules.per_id(message_ids, one))
