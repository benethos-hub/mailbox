"""Microsoft Graph on the wire, for one account: each request with its
access token and the preference for immutable ids, a refused token
renewed once, Graph's pages followed, JSON batches, the well-known
folders, and Graph's errors as this project's."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, TypeVar
from urllib.parse import quote, urlsplit

from pydantic import BaseModel

from ....common.chunks import batched
from ....errors import (
    BadRequestError,
    ChangesExpiredError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...models import FolderRole
from ...protocols import Answer, ApiClient, wire
from .. import rules
from ..base import TokenSource
from . import mappers
from .shapes import Batch, ErrorDetail, Failure, Item, Listing, Placed

# DEBUG alone: the data layer decides nothing (docs/LOGGING.md rule 6.2).
# A pause Graph asks for reaches the domain as an error.
log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com"
VERSION = "/v1.0"
# Requests in one JSON batch, Graph's limit.
BATCH_SIZE = 20
# Ids that survive a move (CONCEPT 4.1), asked for on every request.
IMMUTABLE_IDS = 'IdType="ImmutableId"'

S = TypeVar("S", bound=BaseModel)
T = TypeVar("T")
L = TypeVar("L", bound=Listing[Any])


class Graph:
    def __init__(
        self,
        tokens: TokenSource,
        http: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tokens = tokens
        self._http = http or ApiClient()
        self._clock = clock
        self._roles: dict[str, FolderRole] | None = None
        self._root: str | None = None
        # Until when Graph asked to be left alone (Retry-After).
        self._rest_until = 0.0

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> Answer:
        """One Graph request. ``path`` below ``/v1.0``, e.g. ``/me/messages``.
        While Graph asked to be left alone, nothing is sent."""
        wait = self._rest_until - self._clock()
        if wait > 0:
            raise rules.resting("microsoft asked to wait", wait)
        for attempt in (1, 2):
            token = await self.tokens.access_token()
            headers = {
                "Authorization": f"Bearer {token.get_secret_value()}",
                "Prefer": IMMUTABLE_IDS,
            }
            if content_type:
                headers["Content-Type"] = content_type
            answer = await self._http.request(
                method,
                f"{GRAPH}{VERSION}{path}",
                headers=headers,
                params=params,
                json_body=json_body,
                content=content,
            )
            if answer.status == 401 and attempt == 1:
                # Revoked or changed since it was issued: one more try with
                # a new one.
                self.tokens.reject()
                continue
            if not answer.ok:
                rest = _retry_after(answer) if answer.status in (429, 503) else 0.0
                self._rest_until = self._clock() + rest
                if rest > 0:
                    log.debug("microsoft asked to wait %.0fs", rest)
                raise _failure(answer)
            return answer
        raise AssertionError("unreachable")  # pragma: no cover

    async def read(self, shape: type[S], method: str, path: str, **kwargs: Any) -> S:
        """One Graph request, its answer read as ``shape``."""
        answer = await self.call(method, path, **kwargs)
        return wire.parse(
            shape, answer.body, "microsoft answered in a shape of its own"
        )

    async def pages(self, first: L) -> AsyncIterator[L]:
        """``first`` and every page after it, as Graph links them."""
        page = first
        while True:
            yield page
            if not page.next_link:
                return
            page = await self.read(type(page), "GET", own_path(page.next_link))

    async def all(
        self, listing: type[Listing[T]], path: str, params: Mapping[str, str]
    ) -> list[T]:
        """Every item of a list, following Graph's pages. ``listing``
        names what the items are, e.g. ``Listing[MailFolder]``."""
        items: list[T] = []
        first = await self.read(listing, "GET", path, params=params)
        async for page in self.pages(first):
            items.extend(page.value)
        return items

    async def batch(self, urls: list[str], batch: type[Batch[T]]) -> dict[int, T]:
        """GET each of ``urls`` under immutable ids, twenty to a JSON
        batch. The body of each answered with 200, by its index.
        ``batch`` names what the bodies are, e.g. ``Batch[Message]``."""
        bodies: dict[int, T] = {}
        for chunk in batched(list(enumerate(urls)), BATCH_SIZE):
            requests = [
                {
                    "id": str(n),
                    "method": "GET",
                    "url": url,
                    "headers": {"Prefer": IMMUTABLE_IDS},
                }
                for n, url in chunk
            ]
            answer = await self.read(
                batch, "POST", "/$batch", json_body={"requests": requests}
            )
            for reply in answer.responses:
                if reply.status == 200 and reply.body is not None:
                    bodies[int(reply.id)] = reply.body
        return bodies

    async def move(self, shape: type[S], path: str, destination: str) -> S:
        """Moves the folder or message at ``path``. Graph answers with it
        in its new place."""
        return await self.read(
            shape, "POST", f"{path}/move", json_body={"destinationId": destination}
        )

    async def placed(self, path: str) -> Placed:
        """Where the message at ``path`` is, and whether it is a draft."""
        return await self.read(
            Placed, "GET", path, params={"$select": "parentFolderId,isDraft"}
        )

    async def folder_roles(self) -> dict[str, FolderRole]:
        """The id of each well-known folder the mailbox has, and its role."""
        if self._roles is None:
            roles: dict[str, FolderRole] = {}
            for name, role in mappers.WELL_KNOWN.items():
                try:
                    found = await self.read(
                        Item, "GET", f"/me/mailFolders/{name}", params={"$select": "id"}
                    )
                except NotFoundError:
                    continue
                roles[found.id] = role
            self._roles = roles
        return self._roles

    async def role_id(self, role: FolderRole) -> str:
        for folder_id, found in (await self.folder_roles()).items():
            if found is role:
                return folder_id
        raise rules.no_folder(role)

    async def root_id(self) -> str:
        """The mailbox's root folder, which Graph names as the parent of a
        top-level folder."""
        if self._root is None:
            item = await self.read(Item, "GET", "/me/mailFolders/msgfolderroot")
            self._root = item.id
        return self._root

    def forget(self) -> None:
        """The folders read again: after a new sign-in they may differ."""
        self._roles = None

    async def close(self) -> None:
        await self._http.close()


def id_(value: str | None) -> str:
    """An id as one part of a path."""
    return quote(str(value), safe="")


def own_path(link: str) -> str:
    """The path of a Graph link, e.g. a next page, below ``/v1.0``. Refuses
    any other host: a cursor comes back from the caller, and a forged one
    must not carry the token elsewhere."""
    parts = urlsplit(link)
    if (parts.scheme or parts.netloc) and f"{parts.scheme}://{parts.netloc}" != GRAPH:
        raise rules.invalid_cursor()
    # A full link names the version, but a cursor handed out before does not.
    rest = parts.path.removeprefix(VERSION) if parts.netloc else parts.path
    if not rest.startswith("/me/") or ".." in rest:
        raise rules.invalid_cursor()
    return f"{rest}?{parts.query}" if parts.query else rest


def _retry_after(answer: Answer) -> float:
    """The seconds Graph asks to wait, 0 when it asks nothing."""
    value = answer.headers.get("retry-after", "")
    return float(value) if value.isdigit() else 0.0


def _failure(answer: Answer) -> MailboxServiceError:
    """Graph's error as this project's, with Graph's code and message."""
    found = wire.read(Failure, answer.body)
    error = (found.error if found else None) or ErrorDetail()
    code = error.code or answer.status
    text = f"microsoft: {error.message or 'request failed'} ({code})"
    if answer.status == 401:
        return ProviderAuthError("microsoft refused the access token: sign in again")
    if answer.status == 404:
        return NotFoundError(text)
    if answer.status == 409:
        return ConflictError(text)
    if answer.status == 410:
        # A delta token Graph no longer keeps.
        return ChangesExpiredError(text)
    if answer.status == 400:
        return BadRequestError(text)
    if answer.status in (429, 502, 503, 504):
        wait = _retry_after(answer)
        later = f", retry after {wait:.0f}s" if wait else ""
        return ProviderUnavailableError(f"microsoft is busy{later} ({code})")
    return ProviderError(text)
