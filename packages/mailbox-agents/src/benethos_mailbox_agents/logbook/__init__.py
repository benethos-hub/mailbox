"""Every line on stderr, one activity class per line (docs/mailbox-agents/LOGGING.md).

No other module of the package imports :mod:`logging`. A module that has
something to say builds the activity of the catalogue that says it and
hands it to :func:`record`. The class decides what a line may carry: ids,
states, counts, durations and the class and code of an error. Never a
subject, a sender, the text of a mail, an attachment name, a token or a
key, and never the message of an error, which may quote what an upstream
answered. See docs/mailbox-agents/concept/safety.md.
"""

from __future__ import annotations

from .activity import Activity, Failure, describe, escaped, record
from .catalogue import actions, feed, messages, process, worker
from .output import LIBRARIES, configure

__all__ = [
    "LIBRARIES",
    "Activity",
    "Failure",
    "actions",
    "configure",
    "describe",
    "escaped",
    "feed",
    "messages",
    "process",
    "record",
    "worker",
]
