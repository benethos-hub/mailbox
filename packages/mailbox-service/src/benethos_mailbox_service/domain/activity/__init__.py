"""Activities: what was done in the service, and by whom (docs/LOGGING.md
section 7).

A domain service builds an activity from ``catalogue`` and hands it to
``ActivityLog.record``, which writes its line. It writes no line of its
own.

An activity is not a change. A change is what changed in a mailbox, such
as ``message.created``: it stays with ``domain/changes.py`` and goes to
clients through the change feed and webhooks. An activity goes to the
log. The word "event" is kept free for neither.
"""

from __future__ import annotations

from .base import (
    DISPATCHER,
    HOST,
    SERVICE,
    WORKER,
    Activity,
    Actor,
    Failure,
    someone,
)
from .recorder import ActivityLog

__all__ = [
    "DISPATCHER",
    "HOST",
    "SERVICE",
    "WORKER",
    "Activity",
    "ActivityLog",
    "Actor",
    "Failure",
    "someone",
]
