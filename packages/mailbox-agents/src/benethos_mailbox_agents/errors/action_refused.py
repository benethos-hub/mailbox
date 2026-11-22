"""The error ``ActionRefusedError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["ActionRefusedError"]


class ActionRefusedError(MailboxAgentError):
    """The runtime refused an action: one the agent did not declare, an
    account it does not work on, a keyword not its own, a folder that does
    not exist, or a message or folder in or below the trash, junk or
    spam."""

    code = "action_refused"
