"""``serve``: the REST API and the UI, with the log configured first.

Should a background loop end, the server stops and the command ends with
an error, so a supervisor such as ``restart: unless-stopped`` starts the
service anew instead of leaving it answering without its sync and its
webhooks."""

from __future__ import annotations

import argparse
from typing import Any

from ..config import load_settings, settings_file
from .common import Commands


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    serve = commands.add_parser("serve", help="run the REST API", parents=[option])
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)


# The exit code of uvicorn.run for a server that never started. Older
# releases of uvicorn do not export the name.
STARTUP_FAILURE = 3


class _Stop:
    """Ends the server once it runs, and remembers that it did."""

    def __init__(self) -> None:
        self.server: Any = None
        self.asked = False

    def __call__(self) -> None:
        self.asked = True
        if self.server is not None:
            self.server.should_exit = True


def run(args: argparse.Namespace) -> None:
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
    # The log names the settings and the database once the app starts.
    app = assembly.create_app(
        settings, logbook=book, settings_file=settings_file(args.env_file), stop=stop
    )
    # What uvicorn.run does for one process without reload: the server
    # built here, so a loop that ends can stop it.
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
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        sys.exit(STARTUP_FAILURE)
    if stop.asked:
        raise MailboxServiceError("a background loop ended, the service stopped")
