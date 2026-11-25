"""What the live checks of the agents share, one module per subject.

A live check runs against the test account of containers/live/mailbox-agents/ and no
other. So its settings come from its file and from nothing else: a
setting exported in the shell, of a real deployment say, is not read, and
cannot point a check at a real account. A mailbox service that is not on
this machine stops the check with exit code 2 (decided 2026-11-18). The
account and the service are printed before the check reads or writes.

- ``settings``: where the live setup is, and the settings of a check from
  their file alone.
- ``upstreams``: the mailbox service and the model gateway of the
  settings, and a worker over them.
- ``snapshots``: how the messages of the test account lie, and their mail
  put back after a check.
- ``checks``: the run of the checks, a check skipped, the agent
  ``sorting`` over the test account and the keywords it sets, and the
  labels a state file holds.

The live scripts import this package beside them, as ``agents_common``,
and the invented mail of containers/live/mailbox-agents/mail.py through
it, as ``mail``.
"""

from __future__ import annotations

import sys

from .checks import Skip, labels, run_checks, sort_test_account, sorting_keywords
from .settings import (
    DAYS,
    ENV,
    LIST,
    LIVE,
    LIVE_PORT,
    LOOPBACK,
    ROOT,
    live_settings,
    parse_settings,
)
from .snapshots import Snapshot, inbox_snapshot, put_back, snapshot
from .upstreams import connect_mailbox, open_gateway, worker

sys.path.insert(0, str(LIVE))

import mail  # beside the setup, not a package

__all__ = [
    "DAYS",
    "ENV",
    "LIST",
    "LIVE",
    "LIVE_PORT",
    "LOOPBACK",
    "ROOT",
    "Skip",
    "Snapshot",
    "connect_mailbox",
    "inbox_snapshot",
    "labels",
    "live_settings",
    "mail",
    "open_gateway",
    "parse_settings",
    "put_back",
    "run_checks",
    "snapshot",
    "sort_test_account",
    "sorting_keywords",
    "worker",
]
