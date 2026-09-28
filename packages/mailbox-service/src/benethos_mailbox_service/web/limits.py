"""The size of a request body, for both front ends.

A request whose body is larger than ``MAX_BODY`` is refused with ``413``
before the service reads it all: when its ``Content-Length`` says so,
at once, and when it comes in chunks, as soon as it grows past the limit.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..common.sizes import MIB, megabytes
from ..domain.activity import ActivityLog, someone
from ..domain.activity import http as said

# The largest mail the service sends carries 25 MB of attachments, which
# base64 in a JSON body makes about 34 MB.
MAX_BODY = 40 * MIB


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
            413, f"the request is larger than {megabytes(self._limit)}"
        )

    @staticmethod
    def _activity(scope: Scope) -> ActivityLog:
        """The service's activity log, where the app has one."""
        app = scope.get("app")
        services = getattr(getattr(app, "state", None), "services", None)
        found = getattr(services, "activity", None)
        return found if isinstance(found, ActivityLog) else ActivityLog()


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
