"""Sending, drafts, idempotency, the send limit (docs/LOGGING.md 5.6,
5.9).

Drafts are mail content and change nothing others see: not logged. A
send names the count of its recipients, never their addresses: those are
in the audit of sends alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from ....common.clock import log_time
from ....common.text import plural
from ....data.models import Account
from ..base import Activity, Failure, account


@dataclass(frozen=True, kw_only=True)
class MessageSent(Activity):
    name: ClassVar[str] = "sent"

    account: Account
    recipients: int
    # The sent copy, else the Message-ID the message went out with.
    message: str

    def says(self) -> str:
        return (
            f"sent a message from {account(self.account)} to "
            f"{plural(self.recipients, 'recipient')}: {self.message}"
        )


@dataclass(frozen=True, kw_only=True)
class SendRefused(Activity):
    """The grants do not allow the send, ``denied`` in the audit of sends.
    The reason is the error's code, as in the audit: its message may name
    a recipient."""

    name: ClassVar[str] = "refused"
    level: ClassVar[int] = logging.WARNING

    account_id: str
    code: str

    def says(self) -> str:
        return f"was refused to send from {self.account_id}"

    def why(self) -> str:
        return self.code


@dataclass(frozen=True, kw_only=True)
class SendFailed(Activity):
    """The provider did not take the message, ``failed`` in the audit of
    sends. The reason is the error's code: a mail server's answer may name
    a recipient."""

    name: ClassVar[str] = "send_failed"
    level: ClassVar[int] = logging.WARNING

    account_id: str
    code: str

    def says(self) -> str:
        return f"could not send from {self.account_id}"

    def why(self) -> str:
        return self.code


@dataclass(frozen=True, kw_only=True)
class SentBut(Failure):
    """A step after the message went out failed. The send stands."""

    name: ClassVar[str] = "sent_but"

    account: Account
    what: str

    def says(self) -> str:
        return f"sent a message from {account(self.account)}, but {self.what}"


@dataclass(frozen=True, kw_only=True)
class NotInAudit(Failure):
    name: ClassVar[str] = "not_in_audit"
    level: ClassVar[int] = logging.ERROR

    account_id: str

    def says(self) -> str:
        return (
            f"sent a message from {self.account_id}, but it is not in the audit "
            "of sends"
        )


@dataclass(frozen=True, kw_only=True)
class SendLimitReached(Activity):
    """The grants' limit of mails in 24 hours. The audit of sends has the
    attempt as ``denied``."""

    name: ClassVar[str] = "send_limit"
    level: ClassVar[int] = logging.WARNING

    account_id: str
    reason: str
    retry_after: int

    def says(self) -> str:
        return f"reached the send limit on {self.account_id}"

    def why(self) -> str:
        return f"{self.reason}, the next in {self.retry_after}s"


@dataclass(frozen=True, kw_only=True)
class SendsPurged(Activity):
    """Records older than the audit keeps are gone. The normal course,
    once an hour at most, so no warning."""

    name: ClassVar[str] = "sends_purged"

    count: int
    before: datetime

    def says(self) -> str:
        return (
            f"purged {plural(self.count, 'record')} older than "
            f"{log_time(self.before)} from the audit of sends"
        )


@dataclass(frozen=True, kw_only=True)
class Replayed(Activity):
    """A retry with the same Idempotency-Key got the first result."""

    name: ClassVar[str] = "replayed"
    level: ClassVar[int] = logging.DEBUG

    account_id: str
    operation: str

    def says(self) -> str:
        return (
            f"answered {self.operation} on {self.account_id} with the result of "
            "its Idempotency-Key"
        )


@dataclass(frozen=True, kw_only=True)
class ResultNotKept(Failure):
    """The result of a request with an Idempotency-Key, done but not
    stored: a retry would do it again."""

    name: ClassVar[str] = "result_not_kept"
    level: ClassVar[int] = logging.ERROR

    account_id: str
    operation: str

    def says(self) -> str:
        return (
            f"did {self.operation} on {self.account_id}, but could not keep its "
            "result for the Idempotency-Key"
        )
