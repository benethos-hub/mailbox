"""The catalogue: every line the package writes, one class each, one
module per area (docs/mailbox-agents/LOGGING.md section 6).

A module of the package that has something to say builds an activity of
its area and hands it to ``record``:
``record(messages.StateSet(agent=..., message_id=..., state="done"))``.
"""

from __future__ import annotations

from . import actions, feed, messages, process, worker

__all__ = ["AREAS", "actions", "feed", "messages", "process", "worker"]

AREAS = (process, worker, feed, messages, actions)
