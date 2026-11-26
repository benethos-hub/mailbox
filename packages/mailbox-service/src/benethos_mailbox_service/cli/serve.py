"""``serve``: the REST API and the UI, with the log configured first.

Should a background loop end, the server stops and the command ends with
an error, so a supervisor such as ``restart: unless-stopped`` starts the
service anew instead of leaving it answering without its sync and its
webhooks. On a database server, ``serve`` waits for the database at
start, a while: a server and its database often start together."""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from typing import Any, TypeVar

from ..config import Settings, database_url_parts, load_settings, settings_file
from .common import Commands

T = TypeVar("T")
# Seconds between two attempts to reach the database at start.
START_RETRY = 2.0


class Waiting:
    """The clock and the pause of the waiting at start: a test moves
    them, and nothing else."""

    clock: Callable[[], float] = staticmethod(time.monotonic)
    sleep: Callable[[float], None] = staticmethod(time.sleep)


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    serve = commands.add_parser("serve", help="run the REST API", parents=[option])
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)


# The exit code of uvicorn.run for a server that never started. Older
# releases of uvicorn do not export the name.
STARTUP_FAILURE = 3


class _Stop:
    """Ends the server once it runs, and remembers why."""

    def __init__(self) -> None:
        self.server: Any = None
        self.reason = ""

    def __call__(self, reason: str) -> None:
        self.reason = reason
        if self.server is not None:
            self.server.should_exit = True


def run(args: argparse.Namespace) -> None:
    import contextlib
    import logging.config
    import sys

    import uvicorn

    from .. import assembly
    from ..data.logbook import LogBook
    from ..errors import MailboxServiceError
    from ..logs import log_config, source_of

    settings = load_settings(args.env_file)
    # Before the app is built: building it may warn already.
    # The log page names a source as the console does.
    book = LogBook(source=source_of)
    config = log_config(settings.log_level, book, form=settings.log_format)
    logging.config.dictConfig(config)
    stop = _Stop()
    services = waited(lambda: assembly.build_services(settings, logbook=book), settings)
    with contextlib.ExitStack() as running:
        # Closed at the end also when the server never ran the end of
        # the app, which closes them otherwise. Closing twice does no harm.
        running.callback(services.close)
        # The lock of a running service, taken before the server starts:
        # a second service on a database server ends here with the
        # reason, not in the start of the server.
        held = (
            None
            if services.store is None
            else running.enter_context(services.store.serving())
        )
        # The log names the settings and the database once the app starts.
        app = assembly.create_app(
            settings,
            services=services,
            settings_file=settings_file(args.env_file),
            stop=stop,
            held=held,
        )
        # What uvicorn.run does for one process without reload: the
        # server built here, so a loop that ends can stop it.
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=args.host or settings.host,
                port=args.port or settings.port,
                log_config=config,
                log_level=settings.log_level,
                forwarded_allow_ips=settings.forwarded_allow_ips,
            )
        )
        stop.server = server
        # Ctrl-C at a terminal ends serve as it ended uvicorn.run, without
        # a traceback. The server has shut down by then.
        with contextlib.suppress(KeyboardInterrupt):
            server.run()
    if not server.started:
        sys.exit(STARTUP_FAILURE)
    if stop.reason:
        raise MailboxServiceError(stop.reason)


def waited(build: Callable[[], T], settings: Settings) -> T:
    """What ``build`` makes, which opens the database. On a database
    server tried again for up to ``database_start_wait`` seconds while
    the server cannot be reached, then the last failure, naming the
    host and the role. Any other refusal ends at once: it would not heal
    by waiting. Another storage is tried once."""
    if settings.storage != "postgres" or settings.database_url is None:
        return build()
    return _again(build, settings, clock=Waiting.clock, sleep=Waiting.sleep)


def _again(
    build: Callable[[], T],
    settings: Settings,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> T:
    from ..errors import StorageError, StorageUnavailableError

    end = clock() + settings.database_start_wait
    while True:
        try:
            return build()
        except StorageUnavailableError as exc:
            if clock() + START_RETRY > end:
                parts = database_url_parts(settings.database_url or "")
                failed = (
                    f"the database failed: {exc.cause}" if exc.cause else exc.message
                )
                raise StorageError(
                    f"the database on {parts.hostname} as {parts.username} could not"
                    f" be opened within {settings.database_start_wait} seconds:"
                    f" {failed}"
                ) from None
        sleep(START_RETRY)
