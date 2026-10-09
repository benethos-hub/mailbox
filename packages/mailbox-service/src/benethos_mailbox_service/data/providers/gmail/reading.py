"""What the other parts read the same way: which labels are folders,
messages by id in the format asked for, a list of ids page by page, and
a message's source.

Gmail has no call for several messages at once but a batch of HTTP
requests, which this adapter does not speak. A few requests go at once
instead, as many as ``AT_ONCE``.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

import anyio

from ....common.opaque import from_base64
from ....errors import MailboxServiceError, NotFoundError, ProviderError
from ...models import MessageSummary
from ...protocols import Params
from . import mappers
from .api import GmailApi, id_
from .shapes import GmailMessage, Messages

# Requests in flight at once for one account. Gmail allows 250 units a
# second per user, and a message costs 5.
AT_ONCE = 8
# Ids a page of a list holds, Gmail's most.
PAGE_SIZE = 500
# Gmail's ids of messages: hexadecimal.
_MESSAGE_ID = re.compile(r"^[0-9a-f]{1,32}$")

T = TypeVar("T")


def is_id(value: str) -> bool:
    """Whether ``value`` can be the id of a Gmail message. Any other is not
    found without a request."""
    return bool(_MESSAGE_ID.match(value))


async def known_folders(api: GmailApi) -> set[str]:
    """The ids of the labels that are folders."""
    return {label.id for label in await api.labels() if mappers.is_folder(label)}


async def require_folder(api: GmailApi, folder_id: str) -> None:
    """A folder of the mailbox: a label that is one, or "All Mail"."""
    if folder_id != mappers.ALL_MAIL and folder_id not in await known_folders(api):
        raise _missing_folder(folder_id)


def _missing_folder(folder_id: str) -> NotFoundError:
    return NotFoundError(f"folder {folder_id} not found")


async def get(api: GmailApi, message_id: str, params: Params) -> GmailMessage:
    """One message. Raises ``NotFoundError`` when it is not there."""
    return await api.read(
        GmailMessage, "GET", f"/messages/{id_(message_id)}", params=params
    )


def metadata_params(headers: tuple[str, ...]) -> list[tuple[str, str]]:
    return [("format", "metadata"), *(("metadataHeaders", h) for h in headers)]


async def at_once(
    keys: Iterable[str], fetch: Callable[[str], Awaitable[T]]
) -> dict[str, T]:
    """``fetch`` for each key, as many as ``AT_ONCE`` at a time. What is
    not found is left out. Any other failure stops it all and is raised."""
    found: dict[str, T] = {}
    failures: list[MailboxServiceError] = []
    limiter = anyio.CapacityLimiter(AT_ONCE)

    async def one(key: str) -> None:
        async with limiter:
            if failures:
                return
            try:
                found[key] = await fetch(key)
            except NotFoundError:
                return
            except MailboxServiceError as exc:
                failures.append(exc)

    async with anyio.create_task_group() as group:
        for key in dict.fromkeys(keys):
            group.start_soon(one, key)
    if failures:
        raise failures[0]
    return found


async def messages(
    api: GmailApi, message_ids: list[str], params: Params
) -> dict[str, GmailMessage]:
    """The messages that are there."""
    wanted = (i for i in message_ids if is_id(i))
    return await at_once(wanted, lambda i: get(api, i, params))


async def summaries(api: GmailApi, message_ids: list[str]) -> dict[str, MessageSummary]:
    """The summaries of the messages that are there."""
    known = await known_folders(api)
    found = await messages(api, message_ids, metadata_params(mappers.SUMMARY_HEADERS))
    return {i: mappers.summary(m, known) for i, m in found.items()}


async def summary(api: GmailApi, message_id: str) -> MessageSummary | None:
    return (await summaries(api, [message_id])).get(message_id)


async def with_source(api: GmailApi, message_id: str) -> GmailMessage:
    """A message with its labels and its source."""
    return await get(api, message_id, {"format": "raw"})


def source(message: GmailMessage) -> bytes:
    """The source of a message in the format ``raw``."""
    if not message.raw:
        raise ProviderError("gmail sent a message without its source")
    try:
        return from_base64(message.raw)
    except ValueError:
        raise ProviderError("gmail sent a source that is not base64") from None


async def ids(api: GmailApi, params: list[tuple[str, str]]) -> list[str]:
    """Every id of a list, page by page."""
    found: list[str] = []
    token: str | None = None
    while True:
        page = [("maxResults", str(PAGE_SIZE)), *params]
        if token:
            page.append(("pageToken", token))
        answer = await api.read(Messages, "GET", "/messages", params=page)
        found += [m.id for m in answer.messages]
        token = answer.next_page_token
        if not token:
            return found


def folder_params(folder_id: str | None) -> list[tuple[str, str]]:
    """What narrows a list to a folder. Without one: every message, the
    trash and the spam among them."""
    if folder_id is None:
        return [("includeSpamTrash", "true")]
    if folder_id == mappers.ALL_MAIL:
        return []
    found = [("labelIds", folder_id)]
    if folder_id in mappers.OUTSIDE_ALL:
        found.append(("includeSpamTrash", "true"))
    return found
