"""The Gmail API on the wire, for one account: each request with its
access token, a refused token renewed once, a pause Gmail asks for kept,
the labels kept a minute, and Gmail's errors as this project's."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar
from urllib.parse import quote

from pydantic import BaseModel

from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...protocols import Answer, ApiClient, Params, refused, wire
from .. import rules
from ..base import TokenSource
from .shapes import Failure, Label, Labels

# DEBUG alone: the data layer decides nothing (docs/LOGGING.md rule 6.2).
log = logging.getLogger(__name__)

GMAIL = "https://gmail.googleapis.com"
MAILBOX = "/gmail/v1/users/me"
# How long the labels are taken as they were: a label made elsewhere
# shows up after this at the latest.
LABELS_FOR = 60.0
# Why Gmail answers 403 when it wants to be asked less often.
_SLOW_DOWN = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})

S = TypeVar("S", bound=BaseModel)


class GmailApi:
    def __init__(
        self,
        tokens: TokenSource,
        http: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tokens = tokens
        self._http = http or ApiClient()
        self._clock = clock
        self._labels: list[Label] | None = None
        self._labels_at = 0.0
        # Until when Gmail asked to be left alone (Retry-After).
        self._rest_until = 0.0

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: Params | None = None,
        json_body: Any = None,
    ) -> Answer:
        """One request. ``path`` below the mailbox, e.g. ``/messages``.
        While Gmail asked to be left alone, nothing is sent."""
        wait = self._rest_until - self._clock()
        if wait > 0:
            raise rules.resting("gmail asked to wait", wait)
        for attempt in (1, 2):
            token = await self.tokens.access_token()
            answer = await self._http.request(
                method,
                f"{GMAIL}{MAILBOX}{path}",
                headers={"Authorization": f"Bearer {token.get_secret_value()}"},
                params=params,
                json_body=json_body,
            )
            if answer.status == 401 and attempt == 1:
                # Revoked or changed since it was issued: one more try with
                # a new one.
                self.tokens.reject()
                continue
            if not answer.ok:
                failure = _failure(answer)
                rest = answer.retry_after
                if isinstance(failure, ProviderUnavailableError) and rest > 0:
                    self._rest_until = self._clock() + rest
                    log.debug("gmail asked to wait %.0fs", rest)
                raise failure
            return answer
        raise AssertionError("unreachable")  # pragma: no cover

    async def read(self, shape: type[S], method: str, path: str, **kwargs: Any) -> S:
        """One request, its answer read as ``shape``."""
        answer = await self.call(method, path, **kwargs)
        return wire.parse(shape, answer.body, "gmail answered in a shape of its own")

    async def labels(self) -> list[Label]:
        """Every label of the mailbox, without counts."""
        if self._labels is None or self._clock() - self._labels_at > LABELS_FOR:
            found = await self.read(Labels, "GET", "/labels")
            self._labels = found.labels
            self._labels_at = self._clock()
        return self._labels

    async def label(self, label_id: str) -> Label:
        """One label, with its counts."""
        return await self.read(Label, "GET", f"/labels/{id_(label_id)}")

    def forget(self) -> None:
        """The labels read again: they changed, or a new sign-in may see
        others."""
        self._labels = None

    async def close(self) -> None:
        await self._http.close()


def id_(value: str) -> str:
    """An id as one part of a path."""
    return quote(value, safe="")


def _failure(answer: Answer) -> MailboxServiceError:
    """Gmail's error as this project's, with Gmail's message and reason."""
    found = wire.read(Failure, answer.body)
    error = found.error if found and found.error else None
    reasons = {r.reason for r in error.errors if r.reason} if error else set()
    message = (error.message if error else None) or "request failed"
    code = next(iter(sorted(reasons)), None) or (error.status if error else None)
    text = f"gmail: {message} ({code or answer.status})"
    if answer.status == 403 and reasons & _SLOW_DOWN:
        return ProviderUnavailableError(f"gmail is busy ({code})")
    errors: Mapping[int, Callable[[str], MailboxServiceError]] = {
        401: lambda _: ProviderAuthError(
            "gmail refused the access token: sign in again"
        ),
        400: BadRequestError,
        403: ProviderError,
        404: NotFoundError,
        409: ConflictError,
    }
    return refused(answer, "gmail", text, errors, code)
