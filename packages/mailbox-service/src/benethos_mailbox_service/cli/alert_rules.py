"""``alert-rules``: the alerts on the figures of ``GET /v1/metrics`` on
stdout, a file for ``rule_files`` of Prometheus."""

from __future__ import annotations

import argparse

from .common import Commands, emit


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    # It reads no settings. The option is there as on every command.
    commands.add_parser(
        "alert-rules",
        help="print the alerts on the metrics as rules of Prometheus",
        parents=[option],
    )


def run(args: argparse.Namespace) -> None:
    from ..assembly import alert_rules

    # emit ends the file with its line break.
    emit(alert_rules().removesuffix("\n"))
