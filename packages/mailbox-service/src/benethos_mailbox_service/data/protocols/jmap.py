"""JMAP (RFC 8620, 8621) over ``http``: the session, method calls, blobs
and the event stream.

Speaks the protocol and nothing else: no folders or messages of the API,
no decisions. JMAP's own errors leave it as ``MailboxServiceError``.

Every URL the session names is used on the server the account names: its
path and query, never its host or port. So the credential goes to no other
host, and a server that names itself otherwise, behind a proxy or by a
name only its own network knows, still works.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import anyio

from ...errors import (
    BadRequestError,
    ChangesExpiredError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from .http import Answer, ServerClient
from .transport import Pick

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

# One call: the method, its arguments, and the tag that pairs it with its
# response.
Invocation = tuple[str, dict[str, Any], str]


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
    capabilities: Mapping[str, Any]
    # The capabilities of the account, e.g. what submission it allows.
    account_capabilities: Mapping[str, Any]

    def offers(self, capability: str) -> bool:
        return capability in self.capabilities and (
            capability == CORE or capability in self.account_capabilities
        )

    def limit(self, name: str, default: int) -> int:
        value = (self.capabilities.get(CORE) or {}).get(name)
        return value if isinstance(value, int) and value > 0 else default


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
                self._limiter = anyio.CapacityLimiter(
                    self._session.limit("maxConcurrentRequests", DEFAULT_CONCURRENT)
                )
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
            return _session(answer.json())
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
        reply = answer.json()
        if not isinstance(reply, dict) or not isinstance(
            reply.get("methodResponses"), list
        ):
            raise ProviderError("the JMAP server answered without method responses")
        if reply.get("sessionState") not in (None, session.state):
            self._stale = True
        responses: list[Invocation] = []
        for item in reply["methodResponses"]:
            if (
                isinstance(item, list)
                and len(item) == 3
                and isinstance(item[0], str)
                and isinstance(item[1], dict)
                and isinstance(item[2], str)
            ):
                responses.append((item[0], item[1], item[2]))
        return responses

    async def upload(self, data: bytes, content_type: str) -> str:
        """Store ``data`` as a blob of the account. Its blob id."""
        session = await self.session()
        path = _expand(session.upload, accountId=session.account_id)
        answer = await self._limited(
            "POST", path, content=data, headers={"Content-Type": content_type}
        )
        if not answer.ok:
            raise _failure(answer, "upload")
        reply = answer.json()
        blob_id = reply.get("blobId") if isinstance(reply, dict) else None
        if not isinstance(blob_id, str):
            raise ProviderError("the JMAP server answered an upload without a blob id")
        return blob_id

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
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
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


# --- reading answers ------------------------------------------------------------------


def result(responses: list[Invocation], tag: str) -> dict[str, Any]:
    """The arguments of the response to the call ``tag``. A method error
    raises as this project's error."""
    for name, args, answered in responses:
        if answered == tag:
            if name == "error":
                raise method_error(args)
            return args
    raise ProviderError("the JMAP server left a call unanswered")


def error_type(responses: list[Invocation], tag: str) -> str | None:
    """The type of the method error the call ``tag`` met, None without one."""
    for name, args, answered in responses:
        if answered == tag and name == "error":
            return str(args.get("type"))
    return None


def method_error(args: Mapping[str, Any]) -> MailboxServiceError:
    """A method error (RFC 8620 3.6.2) as this project's error."""
    kind = str(args.get("type") or "serverFail")
    text = f"jmap: {args.get('description') or kind} ({kind})"
    if kind == "cannotCalculateChanges":
        return ChangesExpiredError(text)
    if kind in ("serverUnavailable", "rateLimit"):
        return ProviderUnavailableError(text)
    if kind in ("unknownMethod", "unsupportedFilter", "unsupportedSort"):
        return NotSupportedError(text)
    if kind in ("invalidArguments", "requestTooLarge", "anchorNotFound"):
        return BadRequestError(text)
    if kind == "forbidden":
        return ProviderAuthError(text)
    return ProviderError(text)


def set_error(error: Mapping[str, Any], what: str) -> MailboxServiceError:
    """A SetError (RFC 8620 5.3) for one object as this project's error.
    ``what``: what the object is, e.g. "message"."""
    kind = str(error.get("type") or "serverFail")
    text = f"jmap: {error.get('description') or kind} ({kind})"
    if kind == "notFound":
        return NotFoundError(f"{what} not found")
    if kind in (
        "alreadyExists",
        "mailboxHasChild",
        "mailboxHasEmail",
        "overQuota",
        "stateMismatch",
        "willDestroy",
    ):
        return ConflictError(text)
    if kind in ("invalidProperties", "invalidPatch", "tooLarge", "singleton"):
        return BadRequestError(text)
    if kind in ("forbidden", "forbiddenFrom", "forbiddenToSend", "forbiddenMailFrom"):
        return ConflictError(text)
    return ProviderError(text)


def _session(body: Any) -> Session:
    if not isinstance(body, dict):
        raise ProviderError("the JMAP session is no JSON object")
    capabilities = body.get("capabilities") or {}
    primary = (body.get("primaryAccounts") or {}).get(MAIL)
    if CORE not in capabilities or MAIL not in capabilities or not primary:
        raise ProviderError("the server offers no JMAP mail for this login")
    account = (body.get("accounts") or {}).get(primary) or {}
    try:
        return Session(
            account_id=str(primary),
            api=_own(body["apiUrl"]),
            download=_own(body["downloadUrl"]),
            upload=_own(body["uploadUrl"]),
            events=_own(body["eventSourceUrl"]) if body.get("eventSourceUrl") else None,
            state=str(body.get("state") or ""),
            capabilities=capabilities,
            account_capabilities=account.get("accountCapabilities") or {},
        )
    except (KeyError, TypeError):
        raise ProviderError("the JMAP session lacks a URL it must name") from None


def _own(url: Any) -> str:
    """The path and query of a URL the session names, for the server the
    account names (see the module's docstring)."""
    if not isinstance(url, str):
        raise TypeError(url)
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


async def _state_changes(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """The ``changed`` map of each ``state`` event. Pings and other events
    pass by."""
    event = ""
    data: list[str] = []
    async for line in lines:
        if line == "":
            if event in ("", "state") and data:
                try:
                    found = json.loads("\n".join(data))
                except ValueError:
                    found = None
                if isinstance(found, dict) and isinstance(found.get("changed"), dict):
                    yield found["changed"]
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
    detail = ""
    try:
        problem = answer.json()
    except ProviderError:
        problem = None
    if isinstance(problem, dict):
        detail = str(problem.get("detail") or problem.get("type") or "")
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
