"""Activities: what was done in the service, and by whom (docs/LOGGING.md
section 7).

The catalogue has one module per area, and this package offers each:
a domain service imports its area, ``from ..activity import mailbox as
said``, builds an activity such as ``said.MessageSent(...)`` and hands
it to ``ActivityLog.record``, which writes its line. It writes no line
of its own.

An activity is not a change. A change is what changed in a mailbox, such
as ``message.created``: it stays with ``domain/changes/`` and goes to
clients through the change feed and webhooks. An activity goes to the
log. The word "event" is kept free for neither.
"""

from __future__ import annotations

from .audit import Audit, audited
from .base import (
    DISPATCHER,
    HOST,
    PASSWORD,
    SERVICE,
    WORKER,
    Activity,
    Actor,
    Failure,
    someone,
)
from .catalogue import (
    accounts,
    auth,
    changes,
    discovery,
    http,
    mailbox,
    sync,
    system,
    users,
    webhooks,
)
from .recorder import ActivityLog

__all__ = [
    "DISPATCHER",
    "HOST",
    "PASSWORD",
    "SERVICE",
    "WORKER",
    "Activity",
    "ActivityLog",
    "Audit",
    "Actor",
    "Failure",
    "accounts",
    "audited",
    "auth",
    "changes",
    "discovery",
    "http",
    "mailbox",
    "someone",
    "sync",
    "system",
    "users",
    "webhooks",
]
