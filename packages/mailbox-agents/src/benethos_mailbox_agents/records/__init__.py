"""The models passed between the layers. Data only, no behaviour beyond
what reads a field."""

from __future__ import annotations

from .decisions import LABEL, Decision, Evidence, Step, StepResult
from .items import KEYWORD_REMOVED, MESSAGE_GONE, OpenItem
from .mail import (
    DISCARD_ROLES,
    EVENTS,
    Address,
    Attachment,
    Event,
    FolderRef,
    MailMessage,
    MessageRef,
    Thread,
)

__all__ = [
    "DISCARD_ROLES",
    "EVENTS",
    "KEYWORD_REMOVED",
    "LABEL",
    "MESSAGE_GONE",
    "Address",
    "Attachment",
    "Decision",
    "Event",
    "Evidence",
    "FolderRef",
    "MailMessage",
    "MessageRef",
    "OpenItem",
    "Step",
    "StepResult",
    "Thread",
]
