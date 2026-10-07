"""The client of one JMAP account: the session, method calls, blobs and
the event stream."""

from __future__ import annotations

import math
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import anyio

from ....errors import (
    BadRequestError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from .. import wire
from ..http import Answer, ServerClient
from ..transport import Pick
from .shapes import (
    AccountShape,
    Capabilities,
    Invocation,
    Limits,
    Problem,
    Reply,
    SessionResource,
    StateChange,
    States,
    Uploaded,
)

CORE = "urn:ietf:params:jmap:core"
MAIL = "urn:ietf:params:jmap:mail"
SUBMISSION = "urn:ietf:params:jmap:submission"

DEFAULT_PATH = "/.well-known/jmap"
DEFAULT_PORT = 443
MAX_REDIRECTS = 3
# What the session limits when it says nothing (RFC 8620 2).
DEFAULT_CONCURRENT = 4
DEFAULT_CALLS = 16
DEFAULT_GET = 500


@dataclass(frozen=True)
class JmapServer:
    """Where an account's session resource is."""

    host: str
    port: int = DEFAULT_PORT
    path: str = DEFAULT_PATH
    # Checks the host at each request. Without: connect by name.
    pick: Pick | None = field(default=None, compare=False)

    def url(self, path: str) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}:{self.port}{path}"


@dataclass(frozen=True)
class Session:
    """What the session resource says, its URLs as paths on the server."""

    account_id: str
    api: str
    download: str
    upload: str
    events: str | None
    state: str
    capabilities: frozenset[str]
    # The capabilities of the account, e.g. whether it may send.
    account_capabilities: frozenset[str]
    # The core capability's limits (RFC 8620 2).
    max_concurrent: int = DEFAULT_CONCURRENT
    max_get: int = DEFAULT_GET

    def offers(self, capability: str) -> bool:
        return capability in self.capabilities and (
            capability == CORE or capability in self.account_capabilities
        )


def is_session(body: bytes) -> bool:
    """Whether ``body`` is a JMAP session resource."""
    found = wire.read(Capabilities, body)
    return found is not None and CORE in found.capabilities


class JmapClient:
    def __init__(
        self,
        server: JmapServer,
        authorization: Callable[[], str],
        http: ServerClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``authorization`` gives the value of the Authorization header,
        read for each request and not kept."""
        self._server = server
        self._authorization = authorization
        self._http = http or ServerClient(pick=server.pick)
        self._clock = clock
        self._session: Session | None = None
        self._stale = False
        self._session_lock = anyio.Lock()
        self._limiter: anyio.CapacityLimiter | None = None
        # Until when the server asked to be left alone (Retry-After).
        self._rest_until = 0.0

    # --- the session ----------------------------------------------------------------

    async def session(self, fresh: bool = False) -> Session:
        """The session, read once and again when the server says it
        changed. ``fresh`` reads it again now, e.g. to check a login."""
        async with self._session_lock:
            if self._session is None or self._stale or fresh:
                self._session = await self._read_session()
                self._stale = False
                self._limiter = anyio.CapacityLimiter(self._session.max_concurrent)
            return self._session

    async def _read_session(self) -> Session:
        path = self._server.path
        for _ in range(MAX_REDIRECTS + 1):
            answer = await self._send("GET", path)
            if answer.status in (301, 302, 303, 307, 308):
                path = self._redirect(answer)
                continue
            if not answer.ok:
                raise _failure(answer, "session")
            return _session(answer.body)
        raise ProviderError(
            f"the JMAP session redirects more than {MAX_REDIRECTS} times"
        )

    def _redirect(self, answer: Answer) -> str:
        """The path a redirect points to, on the same server only: the
        credential goes with every request."""
        location = answer.headers.get("location") or ""
        parts = urlsplit(location)
        if parts.netloc:
            same = (
                parts.scheme == "https"
                and (parts.hostname or "").lower() == self._server.host.lower()
                and (parts.port or DEFAULT_PORT) == self._server.port
            )
            if not same:
                raise ProviderError(
                    "the JMAP session redirects to another server: name that "
                    "server in the settings"
                )
        if not parts.path.startswith("/"):
            raise ProviderError("the JMAP session redirects without a path")
        return parts.path + (f"?{parts.query}" if parts.query else "")

    # --- calls ----------------------------------------------------------------------

    async def call(
        self, calls: list[Invocation], using: Iterable[str] = (CORE, MAIL)
    ) -> list[Invocation]:
        """One request with ``calls``. The responses in their order, a method
        error among them as ``("error", {...}, tag)``: ``result`` reads one."""
        session = await self.session()
        body = {
            "using": list(using),
            "methodCalls": [[name, args, tag] for name, args, tag in calls],
        }
        answer = await self._limited("POST", session.api, json_body=body)
        if not answer.ok:
            raise _failure(answer, "request")
        reply = wire.parse(
            Reply, answer.body, "the JMAP server answered without method responses"
        )
        if reply.session_state not in (None, session.state):
            self._stale = True
        return [item for item in reply.method_responses if item is not None]

    async def upload(self, data: bytes, content_type: str) -> str:
        """Store ``data`` as a blob of the account. Its blob id."""
        session = await self.session()
        path = _expand(session.upload, accountId=session.account_id)
        answer = await self._limited(
            "POST", path, content=data, headers={"Content-Type": content_type}
        )
        if not answer.ok:
            raise _failure(answer, "upload")
        return wire.parse(
            Uploaded,
            answer.body,
            "the JMAP server answered an upload without a blob id",
        ).blob_id

    async def download(self, blob_id: str, name: str, content_type: str) -> bytes:
        session = await self.session()
        path = _expand(
            session.download,
            accountId=session.account_id,
            blobId=blob_id,
            name=name,
            type=content_type,
        )
        answer = await self._limited("GET", path)
        if not answer.ok:
            raise _failure(answer, "download")
        return answer.body

    # --- the event stream -----------------------------------------------------------

    @asynccontextmanager
    async def events(
        self, types: str, ping: int, wait: float
    ) -> AsyncIterator[AsyncIterator[Mapping[str, States | None]]]:
        """The server's state changes (RFC 8620 7.3) while the stream is
        open: each the ``changed`` map of a StateChange. ``ping``: the
        seconds between the server's pings, ``wait`` how long a read waits
        for a line. Without an event source ``NotSupportedError``."""
        session = await self.session()
        if session.events is None:
            raise NotSupportedError("the JMAP server offers no event source")
        path = _expand(session.events, types=types, closeafter="no", ping=str(ping))
        headers = {**self._headers(), "Accept": "text/event-stream"}
        async with self._http.lines(
            self._server.url(path), headers=headers, wait=wait
        ) as (answer, lines):
            if not answer.ok:
                raise _failure(answer, "event source")
            yield _state_changes(lines)

    async def close(self) -> None:
        await self._http.close()

    # --- plumbing -------------------------------------------------------------------

    async def _limited(self, method: str, path: str, **kwargs: Any) -> Answer:
        """A request within the server's limit of concurrent requests."""
        limiter = self._limiter or anyio.CapacityLimiter(DEFAULT_CONCURRENT)
        async with limiter:
            return await self._send(method, path, **kwargs)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> Answer:
        """One request to a path on the server. While the server asked to
        be left alone, nothing is sent."""
        wait = self._rest_until - self._clock()
        if wait > 0:
            raise ProviderUnavailableError(
                f"the JMAP server asked to wait: next attempt in {math.ceil(wait)}s"
            )
        answer = await self._http.request(
            method,
            self._server.url(path),
            headers={**self._headers(), **(headers or {})},
            **kwargs,
        )
        if answer.status in (429, 503):
            self._rest_until = self._clock() + _retry_after(answer)
        return answer

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._authorization(), "Accept": "application/json"}


def _session(body: bytes) -> Session:
    found = wire.parse(
        SessionResource, body, "the JMAP session is no JSON object of its shape"
    )
    primary = found.primary_accounts.get(MAIL)
    if CORE not in found.capabilities or MAIL not in found.capabilities or not primary:
        raise ProviderError("the server offers no JMAP mail for this login")
    if not (found.api_url and found.download_url and found.upload_url):
        raise ProviderError("the JMAP session lacks a URL it must name")
    account = found.accounts.get(primary) or AccountShape()
    core = found.capabilities[CORE] or Limits()
    return Session(
        account_id=primary,
        api=_own(found.api_url),
        download=_own(found.download_url),
        upload=_own(found.upload_url),
        events=_own(found.event_source_url) if found.event_source_url else None,
        state=found.state or "",
        capabilities=frozenset(found.capabilities),
        account_capabilities=frozenset(account.account_capabilities),
        max_concurrent=core.max_concurrent_requests or DEFAULT_CONCURRENT,
        max_get=core.max_objects_in_get or DEFAULT_GET,
    )


def _own(url: str) -> str:
    """The path and query of a URL the session names, for the server the
    account names (see the module's docstring)."""
    parts = urlsplit(url)
    if not parts.path.startswith("/"):
        raise ProviderError("the JMAP session names a URL without a path")
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _expand(template: str, **values: str) -> str:
    """A URL template of the session with its variables filled in (RFC
    6570, level 1)."""
    for name, value in values.items():
        template = template.replace("{" + name + "}", quote(value, safe=""))
    return template


async def _state_changes(
    lines: AsyncIterator[str],
) -> AsyncIterator[Mapping[str, States | None]]:
    """The ``changed`` map of each ``state`` event. Pings and other events
    pass by."""
    event = ""
    data: list[str] = []
    async for line in lines:
        if line == "":
            if event in ("", "state") and data:
                found = wire.read(StateChange, "\n".join(data))
                if found is not None:
                    yield found.changed
            event, data = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))


def _retry_after(answer: Answer) -> float:
    value = answer.headers.get("retry-after", "")
    return float(value) if value.isdigit() else 0.0


def _failure(answer: Answer, what: str) -> MailboxServiceError:
    """A request the server refused as a whole, as this project's error."""
    problem = wire.read(Problem, answer.body) or Problem()
    detail = problem.detail or problem.type
    text = f"jmap {what}: {detail or 'refused'} ({answer.status})"
    if answer.status == 401:
        return ProviderAuthError("the JMAP server refused the credential")
    if answer.status == 403:
        return ProviderAuthError(f"the JMAP server refused access ({what})")
    if answer.status == 404:
        return NotFoundError(text)
    if answer.status == 413:
        return BadRequestError(text)
    if answer.status in (429, 502, 503, 504):
        wait = _retry_after(answer)
        later = f", retry after {wait:.0f}s" if wait else ""
        return ProviderUnavailableError(
            f"the JMAP server is busy{later} ({answer.status})"
        )
    return ProviderError(text)
