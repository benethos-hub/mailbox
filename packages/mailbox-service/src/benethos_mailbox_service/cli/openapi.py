"""``openapi``: the OpenAPI document on stdout."""

from __future__ import annotations

import argparse
import sys

from .common import Commands


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    # It reads no settings. The option is there as on every command.
    commands.add_parser(
        "openapi", help="print the OpenAPI document as JSON", parents=[option]
    )


def run(args: argparse.Namespace) -> None:
    from ..assembly import openapi_json

    sys.stdout.write(openapi_json())
