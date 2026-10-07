"""``serve``: the REST API and the UI, with the log configured first."""

from __future__ import annotations

import argparse

from ..config import load_settings, settings_file
from .common import Commands


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    serve = commands.add_parser("serve", help="run the REST API", parents=[option])
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)


def run(args: argparse.Namespace) -> None:
    import logging.config

    import uvicorn

    from .. import assembly
    from ..data.logbook import LogBook
    from ..logs import log_config, short_source

    settings = load_settings(args.env_file)
    # Before the app is built: building it may warn already.
    # The log page names a source as the console does.
    book = LogBook(source=short_source)
    config = log_config(settings.log_level, book)
    logging.config.dictConfig(config)
    # The log names the settings and the database once the app starts.
    app = assembly.create_app(
        settings, logbook=book, settings_file=settings_file(args.env_file)
    )
    uvicorn.run(
        app,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_config=config,
        log_level=settings.log_level,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )
