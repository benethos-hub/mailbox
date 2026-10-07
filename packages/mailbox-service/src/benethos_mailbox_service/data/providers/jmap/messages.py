"""Messages listed, read, changed and deleted. A change is one
``Email/set``: keywords and mailboxes patched, the messages read back."""

from __future__ import annotations

from typing import Any

from ....errors import MailboxServiceError, missing, missing_message
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
from ...protocols import jmap
from .. import rules
from ..base import Capability
from . import mappers
from .account import JmapAccount
from .shapes import Email

# --- listing and reading ----------------------------------------------------------


async def list_messages(
    account: JmapAccount,
    folder_id: str | None,
    limit: int,
    cursor: str | None,
    search: MessageFilter | None,
) -> Page[MessageSummary]:
    """Without a folder: every folder of the account."""
    if folder_id is not None and not mappers.is_id(folder_id):
        raise missing("folder", folder_id)
    scope = mappers.scope(folder_id, search)
    query: dict[str, Any] = {
        "filter": mappers.query_filter(folder_id, search),
        "sort": mappers.SORT,
        # One more, to tell whether a next page follows.
        "limit": limit + 1,
    }
    start: tuple[str, int] | None = None
    if cursor:
        start = mappers.parse_cursor(cursor, scope)
        query.update(anchor=start[0], anchorOffset=1)
    answers = await _page(account, query)
    if start is not None and jmap.error_type(answers, "q") == "anchorNotFound":
        # Gone since: the next one has moved up to its place.
        del query["anchor"], query["anchorOffset"]
        answers = await _page(account, {**query, "position": start[1]})
    found = jmap.read(answers, "q", jmap.Queried)
    emails = {e.id: e for e in jmap.read(answers, "g", jmap.Got[Email]).items}
    ids = found.ids
    page = ids[:limit]
    capped = found.limit
    more = len(ids) > limit or (
        capped is not None and capped <= limit and len(ids) >= capped
    )
    first = found.position or 0
    return Page[MessageSummary](
        items=[mappers.summary(emails[i]) for i in page if i in emails],
        next_cursor=mappers.cursor(scope, page[-1], first + len(page) - 1)
        if more and page
        else None,
    )


async def _page(account: JmapAccount, query: dict[str, Any]) -> list[jmap.Invocation]:
    """A page of a query and its emails, in one request."""
    owner = await account.id()
    return await account.call(
        ("Email/query", {"accountId": owner, **query}, "q"),
        (
            "Email/get",
            {
                "accountId": owner,
                "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                "properties": mappers.SUMMARY_PROPERTIES,
            },
            "g",
        ),
    )


async def get_message(account: JmapAccount, message_id: str) -> Message:
    email = await account.email(message_id, mappers.SUMMARY_PROPERTIES)
    return mappers.message(email, await account.source(email, message_id))


async def get_raw(account: JmapAccount, message_id: str) -> bytes:
    email = await account.email(message_id, ["blobId"])
    return await account.source(email, message_id)


async def get_attachment(
    account: JmapAccount, message_id: str, attachment_id: str
) -> AttachmentContent:
    raw = await get_raw(account, message_id)
    return convert.attachment(parse.ParsedMessage(raw), attachment_id)


# --- changing ---------------------------------------------------------------------


async def update_messages(
    account: JmapAccount,
    capabilities: frozenset[Capability],
    message_ids: list[str],
    changes: MessageUpdate,
) -> dict[str, MessageSummary | MailboxServiceError]:
    targets = None
    if changes.folder_ids is not None:
        rules.move_target(changes, capabilities)
        targets = list(dict.fromkeys(changes.folder_ids))
        known = {f.id for f in await account.folders()}
        unknown = next((t for t in targets if t not in known), None)
        if unknown is not None:
            return dict.fromkeys(message_ids, missing("folder", unknown))
    current = await account.emails(message_ids, ["keywords", "mailboxIds"])
    patches: dict[str, dict[str, Any]] = {}
    for message_id, email in current.items():
        patch = mappers.keyword_patch(email.keywords, changes)
        if targets is not None and set(targets) != set(email.mailbox_ids):
            patch["mailboxIds"] = dict.fromkeys(targets, True)
        if patch:
            patches[message_id] = patch
    return await _changed(account, message_ids, current, patches)


async def delete_messages(
    account: JmapAccount, message_ids: list[str], permanent: bool
) -> dict[str, MessageSummary | None | MailboxServiceError]:
    if permanent:
        return await _destroyed(account, message_ids)
    trash = await account.role_id(FolderRole.TRASH)
    if trash is None:
        return dict.fromkeys(message_ids, rules.no_folder(FolderRole.TRASH))
    current = await account.emails(message_ids, ["mailboxIds"])
    results: dict[str, MessageSummary | None | MailboxServiceError] = {}
    patches: dict[str, dict[str, Any]] = {}
    for message_id, email in current.items():
        if set(email.mailbox_ids) == {trash}:
            results[message_id] = rules.in_trash_already()
        else:
            patches[message_id] = {"mailboxIds": {trash: True}}
    moved = await _changed(
        account, [i for i in message_ids if i not in results], current, patches
    )
    results.update(moved)
    return {i: results[i] for i in message_ids}


async def _changed(
    account: JmapAccount,
    message_ids: list[str],
    current: dict[str, Email],
    patches: dict[str, dict[str, Any]],
) -> dict[str, MessageSummary | MailboxServiceError]:
    """Apply ``patches``, then each message as it is now, or why not."""
    results: dict[str, MessageSummary | MailboxServiceError] = {
        i: missing_message(i) for i in message_ids if i not in current
    }
    if patches:
        done = await account.one("Email/set", {"update": patches}, jmap.SetResult)
        for message_id, error in done.not_updated.items():
            results[message_id] = _message_error(error, message_id)
    wanted = [i for i in message_ids if i not in results]
    now = await account.emails(wanted, mappers.SUMMARY_PROPERTIES)
    for message_id in wanted:
        email = now.get(message_id)
        results[message_id] = (
            mappers.summary(email) if email else missing_message(message_id)
        )
    return {i: results[i] for i in message_ids}


async def _destroyed(
    account: JmapAccount, message_ids: list[str]
) -> dict[str, MessageSummary | None | MailboxServiceError]:
    results: dict[str, MessageSummary | None | MailboxServiceError] = {
        i: missing_message(i) for i in message_ids if not mappers.is_id(i)
    }
    wanted = [i for i in message_ids if i not in results]
    if wanted:
        done = await account.one("Email/set", {"destroy": wanted}, jmap.SetResult)
        failed = done.not_destroyed
        for message_id in wanted:
            error = failed.get(message_id)
            results[message_id] = (
                _message_error(error, message_id) if error is not None else None
            )
    return {i: results[i] for i in message_ids}


def _message_error(error: jmap.SetError, message_id: str) -> MailboxServiceError:
    if error.type == "notFound":
        return missing_message(message_id)
    return jmap.set_error(error, "message")
