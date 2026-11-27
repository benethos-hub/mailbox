"""The error hierarchy.

Every error of this package derives from :class:`MailboxAgentError`, whose
message is masked on construction: a secret noted with ``redact.note`` of
mailbox-common never survives into the text of an error, however it got
there. A log line names the class of an error and its ``code``,
never its message, see ``logbook``. Each error has a module of its own
here, and every name is imported from this package.
"""

from __future__ import annotations

from .action_refused import ActionRefusedError
from .answer_refused import AnswerRefusedError
from .base import MailboxAgentError
from .changes_expired import ChangesExpiredError
from .config import ConfigError
from .contract import ContractError
from .gateway_unavailable import GatewayUnavailableError
from .invalid import describe_invalid
from .limit_reached import LimitReachedError
from .mailbox_refused import MailboxRefusedError
from .mailbox_unavailable import MailboxUnavailableError
from .message_gone import MessageGoneError
from .service_version import ServiceVersionError
from .state_file import STATE_ERRORS, StateConflictError, StateFileError
from .unavailable import UnavailableError

__all__ = [
    "STATE_ERRORS",
    "ActionRefusedError",
    "AnswerRefusedError",
    "ChangesExpiredError",
    "ConfigError",
    "ContractError",
    "GatewayUnavailableError",
    "LimitReachedError",
    "MailboxAgentError",
    "MailboxRefusedError",
    "MailboxUnavailableError",
    "MessageGoneError",
    "ServiceVersionError",
    "StateConflictError",
    "StateFileError",
    "UnavailableError",
    "describe_invalid",
]
