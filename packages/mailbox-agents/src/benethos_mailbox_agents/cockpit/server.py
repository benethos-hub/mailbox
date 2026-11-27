"""The cockpit on its port: the only module of the cockpit that imports
uvicorn. It serves until SIGINT or SIGTERM, without a log of its own:
uvicorn writes no access line, and the one line of the cockpit says on
which port it serves."""

from __future__ import annotations

import asyncio
from typing import Any

import uvicorn

from ..errors import ConfigError
from ..logbook import process, record
from ..settings import PREFIX

__all__ = ["serve"]

# Who the line of the log names.
NAME = "cockpit"


async def serve(application: Any, host: str, port: int, *, named: bool) -> None:
    """Serve ``application`` until the process is stopped. A port that
    cannot be opened is a ConfigError naming the setting. ``named`` says
    whether the pages show subject and sender."""
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    task = asyncio.create_task(_serve(server, port))
    while not server.started:
        if task.done():
            await task
            raise _refused(port)
        await asyncio.sleep(0.02)
    record(process.CockpitServing(agent=NAME, port=port, named=named))
    await task


async def _serve(server: uvicorn.Server, port: int) -> None:
    try:
        await server.serve()
    except SystemExit:
        # uvicorn ends the process when it cannot open the port.
        raise _refused(port) from None


def _refused(port: int) -> ConfigError:
    return ConfigError(
        f"the cockpit cannot be served on port {port}: correct {PREFIX}COCKPIT_PORT"
    )
