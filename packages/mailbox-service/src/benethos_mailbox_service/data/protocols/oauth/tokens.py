"""The token source of an adapter that signs in with OAuth: the access
token in memory, refreshed shortly before it runs out.

Nothing here decides where the refresh token is kept: the caller hands
in how to read and store it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import anyio
from pydantic import SecretStr

from ....errors import ProviderAuthError
from .client import OAuthClient
from .values import Tokens

# An access token counts as spent this long before it runs out.
MARGIN = timedelta(minutes=1)


class RefreshingTokens:
    """A ``TokenSource``: the access token in memory, refreshed shortly
    before it runs out. A new refresh token is stored at once, before the
    access token is used, so a rotation is never lost."""

    def __init__(
        self,
        client: OAuthClient,
        read_refresh: Callable[[], SecretStr],
        store_refresh: Callable[[SecretStr], None],
        clock: Callable[[], datetime] | None = None,
        current: Tokens | None = None,
        on_refresh: Callable[[], object] | None = None,
    ) -> None:
        """``clock`` defaults to the client's: the one that stamped
        ``expires_at`` decides when a token is spent. ``on_refresh`` is
        called after each refresh, for the log of the service."""
        self._on_refresh = on_refresh
        self._client = client
        self._read = read_refresh
        self._store = store_refresh
        self._clock = clock or client.clock
        self._current = current
        self._lock = anyio.Lock()
        # A refresh the provider refused: asked no more with this token.
        self._refused: ProviderAuthError | None = None

    async def access_token(self) -> SecretStr:
        async with self._lock:
            if self._refused is not None:
                raise self._refused
            if self._current is None or self._spent(self._current):
                self._current = await self._renew()
            return self._current.access_token

    def reject(self) -> None:
        self._current = None

    def forget_refusal(self) -> None:
        self._refused = None

    def _spent(self, tokens: Tokens) -> bool:
        return tokens.expires_at - MARGIN <= self._clock()

    async def _renew(self) -> Tokens:
        old = self._read()
        try:
            tokens = await self._client.refresh(old)
        except ProviderAuthError as exc:
            self._refused = exc
            raise
        new = tokens.refresh_token
        if new is not None and new.get_secret_value() != old.get_secret_value():
            self._store(new)
        if self._on_refresh is not None:
            self._on_refresh()
        return tokens
