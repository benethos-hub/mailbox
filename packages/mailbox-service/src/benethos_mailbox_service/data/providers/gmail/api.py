"""The Gmail API on the wire, for one account: each request with its
access token, a refused token renewed once, an error of Gmail's own side
tried again where that is safe, a pause Gmail asks for kept,
the labels kept a minute, and Gmail's errors as this project's."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anyio
from pydantic import BaseModel

from ....common.ratelimit import backoff
from ....errors import (
    MailboxServiceError,
    ProviderUnavailableError,
)
from ...protocols import (
    Answer,
    ApiClient,
    Params,
    path_part,
    refused,
    standard_refusals,
    wire,
)
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
# Errors of Gmail's own side, such as 500 backendError, which Gmail asks
# to try again with exponential backoff: how often, and the first pause.
_AGAIN = frozenset({500, 502, 503, 504})
ATTEMPTS = 3
FIRST_PAUSE = 1.0
# Requests that change nothing when they run twice, besides GET, PUT and
# DELETE: setting labels, and into and out of the trash.
_SETS = ("/modify", "/batchModify", "/batchDelete", "/trash", "/untrash")

S = TypeVar("S", bound=BaseModel)


class GmailApi:
    def __init__(
        self,
        tokens: TokenSource,
        http: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self.tokens = tokens
        self._http = http or ApiClient()
        self._clock = clock
        self._sleep = sleep
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
        While Gmail asked to be left alone, nothing is sent. A request that
        changes nothing twice is tried again after an error of Gmail's own
        side, with a growing pause, as Gmail asks."""
        wait = self._rest_until - self._clock()
        if wait > 0:
            raise rules.resting("gmail asked to wait", wait)
        tries = ATTEMPTS if _repeatable(method, path) else 1
        for attempt in range(tries):
            if attempt:
                await self._sleep(backoff(attempt - 1, base=FIRST_PAUSE))
            answer = await self._signed(method, path, params, json_body)
            if answer.ok:
                return answer
            if answer.status not in _AGAIN or answer.retry_after > 0:
                break
            log.debug("gmail answered %d on attempt %d", answer.status, attempt + 1)
        failure = _failure(answer)
        rest = answer.retry_after
        if isinstance(failure, ProviderUnavailableError) and rest > 0:
            self._rest_until = self._clock() + rest
            log.debug("gmail asked to wait %.0fs", rest)
        raise failure

    async def _signed(
        self, method: str, path: str, params: Params | None, json_body: Any
    ) -> Answer:
        """One request with the access token, and where Gmail refuses the
        token, revoked or changed since it was issued, once more with a
        new one."""
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
                self.tokens.reject()
                continue
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
        return await self.read(Label, "GET", f"/labels/{path_part(label_id)}")

    def forget(self) -> None:
        """The labels read again: they changed, or a new sign-in may see
        others."""
        self._labels = None

    async def close(self) -> None:
        await self._http.close()


def _repeatable(method: str, path: str) -> bool:
    """Whether a request changes nothing more when it runs twice. A send
    or a new draft would be there twice."""
    return method in ("GET", "PUT", "DELETE") or path.endswith(_SETS)


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
    errors = standard_refusals("gmail refused the access token: sign in again")
    return refused(answer, "gmail", text, errors, code)
