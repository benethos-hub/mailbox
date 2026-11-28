"""An application on a port, in the event loop of the process: served
from when the port is open until the block ends, without a log of its
own. uvicorn writes no access line and believes no forwarded header, so
an address is that of the connection. A port that cannot be opened is a
ConfigError with the text its caller gives."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import uvicorn

from ..errors import ConfigError

__all__ = ["Port"]


class _LeftToTheProcess(uvicorn.Server):
    """uvicorn's server, which leaves SIGINT and SIGTERM to the process:
    it stops, and the port with it."""

    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


class Port:
    """``application`` on ``host`` and ``port``. ``refused`` is the text of
    the ConfigError when the port cannot be opened. With ``own_signals``
    the server ends on SIGINT and SIGTERM itself, else it leaves them to
    the process."""

    def __init__(
        self,
        application: Any,
        host: str,
        port: int,
        refused: str,
        *,
        own_signals: bool,
    ) -> None:
        self._refused = refused
        config = uvicorn.Config(
            application,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
            lifespan="off",
            # The address of a caller is the connection's own: a caller
            # on the same host never names it by a header.
            proxy_headers=False,
        )
        self._server = (
            uvicorn.Server(config) if own_signals else _LeftToTheProcess(config)
        )
        self._task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def serving(self) -> AsyncIterator[None]:
        """Serve from when the port is open until the block ends, also when
        it ends by a cancel: the server closes its port before it ends."""
        task = self._task = asyncio.create_task(self._serve())
        while not self._server.started:
            if task.done():
                await task
                raise ConfigError(self._refused)
            await asyncio.sleep(0.02)
        try:
            yield
        finally:
            self._server.should_exit = True
            await task

    async def ended(self) -> None:
        """Wait until the server ends by itself, on a signal of its own."""
        if self._task is not None:
            await asyncio.shield(self._task)

    async def _serve(self) -> None:
        try:
            await self._server.serve()
        except SystemExit:
            # uvicorn ends the process when it cannot open the port.
            raise ConfigError(self._refused) from None
