"""The cockpit on its port (``serving.port``). It serves until SIGINT
or SIGTERM, without a log of its own: the one line of the cockpit says
on which port it serves."""

from __future__ import annotations

from typing import Any

from ..logbook import process, record
from ..serving.port import Port
from ..settings import PREFIX

__all__ = ["serve"]

# Who the line of the log names.
NAME = "cockpit"


async def serve(application: Any, host: str, port: int, *, named: bool) -> None:
    """Serve ``application`` until the process is stopped. A port that
    cannot be opened is a ConfigError naming the setting. ``named`` says
    whether the pages show subject and sender."""
    served = Port(
        application,
        host,
        port,
        f"the cockpit cannot be served on port {port}: correct {PREFIX}COCKPIT_PORT",
        own_signals=True,
    )
    async with served.serving():
        record(process.CockpitServing(agent=NAME, port=port, named=named))
        await served.ended()
