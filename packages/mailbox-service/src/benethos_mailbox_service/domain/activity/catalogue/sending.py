"""Sending, drafts, idempotency (docs/LOGGING.md 5.6).

Drafts are mail content and change nothing others see: not logged. A
send names the count of its recipients, never their addresses: those are
in the audit of sends alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import Account
from ..base import Activity, Failure, account, plural


@dataclass(frozen=True, kw_only=True)
class MessageSent(Activity):
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

    account: Account
    what: str

    def says(self) -> str:
        return f"sent a message from {account(self.account)}, but {self.what}"


@dataclass(frozen=True, kw_only=True)
class NotInAudit(Failure):
    level: ClassVar[int] = logging.ERROR

    account_id: str

    def says(self) -> str:
        return (
            f"sent a message from {self.account_id}, but it is not in the audit "
            "of sends"
        )


@dataclass(frozen=True, kw_only=True)
class Replayed(Activity):
    """A retry with the same Idempotency-Key got the first result."""

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

    level: ClassVar[int] = logging.ERROR

    account_id: str
    operation: str

    def says(self) -> str:
        return (
            f"did {self.operation} on {self.account_id}, but could not keep its "
            "result for the Idempotency-Key"
        )
