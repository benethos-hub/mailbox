"""The limits of the web layer, for both front ends (docs/LOGGING.md 5.9).

A request whose body is larger than ``MAX_BODY`` is refused with ``413``
before the service reads it all: when its ``Content-Length`` says so,
at once, and when it comes in chunks, as soon as it grows past the limit.

Requests are limited as tokens per minute with a burst of half as many.
A signed-in caller counts per API token or per UI session, where its
credential is checked: ``signed_in``. Any other request counts per client
address, in ``RequestLimit``: before the app sees it where it claims no
credential, else when its answer starts, unless ``signed_in`` counted
it. A wrong credential is slowed down by the sign-in throttle of the
domain as well. A refused request answers ``429`` with ``Retry-After``.
The state is in memory and per process.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from benethos_mailbox_common.values import sizes

from ..common.ratelimit import Clock, TokenBucket
from ..config import Settings
from ..domain.activity import ActivityLog, Actor, someone
from ..domain.activity import http as said
from ..domain.rights import Access
from ..errors import RateLimitedError
from .state import app_limits, app_services

# The largest mail the service sends carries 25 MB of attachments, which
# base64 in a JSON body makes about 34 MB.
MAX_BODY = 40 * sizes.MIB


class BodyLimit:
    """ASGI middleware. The body is counted where the app reads it, so the
    refusal is an ``HTTPException`` that the front end of the request
    answers in its own way."""

    def __init__(self, app: ASGIApp, limit: int | None = None) -> None:
        self._app = app
        self._limit = MAX_BODY if limit is None else limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = _content_length(scope)
        received = 0

        async def limited() -> Message:
            nonlocal received
            if declared is not None and declared > self._limit:
                raise self._too_large(scope)
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._limit:
                    raise self._too_large(scope)
            return message

        await self._app(scope, limited, send)

    def _too_large(self, scope: Scope) -> HTTPException:
        """The refusal, logged here: the domain never sees the request."""
        client = scope.get("client")
        self._activity(scope).record(
            said.BodyTooLarge(
                by=someone(client[0] if client else None),
                path=scope.get("path", ""),
                limit=self._limit,
            )
        )
        return HTTPException(
            413, f"the request is larger than {sizes.megabytes(self._limit)}"
        )

    @staticmethod
    def _activity(scope: Scope) -> ActivityLog:
        return _activity(scope)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


# How many callers are remembered at most. The one idle longest is
# forgotten first, so spoofed addresses cannot grow the memory.
MAX_CALLERS = 10_000
# Answered without a limit: a health check must not fail for others.
UNLIMITED = frozenset({"/health"})


@dataclass(frozen=True)
class Refusal:
    """A request refused: when the next one would pass, and whether the
    caller was refused for the first time since it last passed."""

    seconds: int
    first: bool


class Buckets:
    """A token bucket per caller, ``per_minute`` requests a minute with a
    burst of half as many. 0 lets everything through."""

    def __init__(
        self,
        per_minute: int,
        clock: Clock = time.monotonic,
        max_callers: int = MAX_CALLERS,
    ) -> None:
        self.per_minute = per_minute
        self._clock = clock
        self._max_callers = max_callers
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        # The callers refused since they last passed.
        self._refused: set[str] = set()
        # A page may be answered in a worker thread.
        self._lock = threading.Lock()

    def take(self, caller: str) -> Refusal | None:
        """One request of ``caller``. None when it may pass."""
        if not self.per_minute:
            return None
        with self._lock:
            return self._take(caller)

    def _take(self, caller: str) -> Refusal | None:
        bucket = self._buckets.get(caller)
        if bucket is None:
            burst = max(1, self.per_minute // 2)
            bucket = TokenBucket(self.per_minute, burst, clock=self._clock)
            self._buckets[caller] = bucket
            while len(self._buckets) > self._max_callers:
                gone, _ = self._buckets.popitem(last=False)
                self._refused.discard(gone)
        self._buckets.move_to_end(caller)
        wait = bucket.take()
        if not wait:
            self._refused.discard(caller)
            return None
        first = caller not in self._refused
        self._refused.add(caller)
        return Refusal(max(1, math.ceil(wait)), first)


class RequestLimits:
    """The buckets of one app: signed-in callers and client addresses."""

    def __init__(
        self, signed_in: int, anonymous: int, clock: Clock = time.monotonic
    ) -> None:
        self.signed_in = Buckets(signed_in, clock)
        self.anonymous = Buckets(anonymous, clock)

    @classmethod
    def of(cls, settings: Settings) -> RequestLimits:
        return cls(
            settings.rate_limit_per_minute, settings.rate_limit_anonymous_per_minute
        )


class Credential(Enum):
    """What a request carries, as far as ``RequestLimit`` can tell before
    the app sees it."""

    # Counted against the address at once.
    NONE = "none"
    # A credential the app checks, such as any Authorization header:
    # counted against the address when the answer starts, unless the
    # check counted it as signed in.
    CLAIMED = "claimed"
    # One the service knows already, such as a session of the UI: left
    # to the app.
    KNOWN = "known"


# Where ``signed_in`` notes a request it counted, in the request's state.
_COUNTED = "mailbox_counted"


def signed_in(request: Request, caller: str, access: Access) -> None:
    """Count a request of a signed-in caller: ``caller`` names its API
    token or UI session. Raises ``RateLimitedError`` when none is left."""
    limits = _limits(request.scope)
    request.scope.setdefault("state", {})[_COUNTED] = True
    _take(request.scope, limits.signed_in, caller, Actor.of(access))


class RequestLimit:
    """ASGI middleware: the limit per client address, for every request
    no signed-in caller counted. ``credential`` tells what a request
    carries. ``refuse`` answers a refusal as the front end of the request
    does."""

    def __init__(
        self,
        app: ASGIApp,
        credential: Callable[[Request], Credential],
        refuse: Callable[[Request, RateLimitedError], Response],
    ) -> None:
        self._app = app
        self._credential = credential
        self._refuse = refuse

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNLIMITED:
            await self._app(scope, receive, send)
            return
        # Made here, so that the app's request shares it.
        state = scope.setdefault("state", {})
        request = Request(scope)
        carried = self._credential(request)
        if carried is Credential.NONE:
            try:
                self._count(request)
            except RateLimitedError as exc:
                await self._refuse(request, exc)(scope, receive, send)
                return
        if carried is not Credential.CLAIMED:
            await self._app(scope, receive, send)
            return
        refused = False

        async def counted(message: Message) -> None:
            nonlocal refused
            if message["type"] == "http.response.start" and not state.get(_COUNTED):
                try:
                    self._count(request)
                except RateLimitedError as exc:
                    refused = True
                    await self._refuse(request, exc)(scope, receive, send)
            if not refused:
                await send(message)

        await self._app(scope, receive, counted)

    @staticmethod
    def _count(request: Request) -> None:
        address = request.client.host if request.client else "unknown"
        anonymous = _limits(request.scope).anonymous
        _take(request.scope, anonymous, address, someone(address))


def _take(scope: Scope, buckets: Buckets, caller: str, by: Actor) -> None:
    refusal = buckets.take(caller)
    if refusal is None:
        return
    if refusal.first:
        _activity(scope).record(
            said.RequestsLimited(
                by=by,
                path=scope.get("path", ""),
                per_minute=buckets.per_minute,
                seconds=refusal.seconds,
            )
        )
    raise RateLimitedError(
        f"too many requests, try again in {refusal.seconds} seconds",
        retry_after=refusal.seconds,
    )


def _limits(scope: Scope) -> RequestLimits:
    return app_limits(scope["app"])


def _activity(scope: Scope) -> ActivityLog:
    return app_services(scope["app"]).activity
