"""What the APIs called with an OAuth access token share, Gmail's and
Graph's: the token on each request, renewed once where the server
refuses it, and the pause the server asked for."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, TypeVar

import anyio
from pydantic import BaseModel

from ..protocols import Answer, ApiClient, wire
from . import rules
from .base import TokenSource


async def signed(
    tokens: TokenSource, send: Callable[[str], Awaitable[Answer]]
) -> Answer:
    """``send`` with the access token, and where the server refuses the
    token, revoked or changed since it was issued, once more with a new
    one."""
    answer = await send((await tokens.access_token()).get_secret_value())
    if answer.status != 401:
        return answer
    tokens.reject()
    return await send((await tokens.access_token()).get_secret_value())


S = TypeVar("S", bound=BaseModel)


class TokenApi:
    """An API of one account, called with its access token. ``who`` names
    the provider in an error, and ``call`` is each API's own request."""

    who: ClassVar[str] = ""
    call: Callable[..., Awaitable[Answer]]

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
        # Until when the server asked to be left alone (Retry-After).
        self._rest_until = 0.0

    def _rested(self, who: str) -> None:
        """Refuse to send while the server asked to be left alone."""
        wait = self._rest_until - self._clock()
        if wait > 0:
            raise rules.resting(f"{who} asked to wait", wait)

    async def read(self, shape: type[S], method: str, path: str, **kwargs: Any) -> S:
        """One request, its answer read as ``shape``."""
        answer = await self.call(method, path, **kwargs)
        return wire.parse(
            shape, answer.body, f"{self.who} answered in a shape of its own"
        )

    async def close(self) -> None:
        await self._http.close()
