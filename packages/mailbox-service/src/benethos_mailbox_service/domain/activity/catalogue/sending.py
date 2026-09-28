"""Sending, drafts, idempotency (docs/LOGGING.md 5.6).

Drafts are mail content and change nothing others see: not logged. A
send names the count of its recipients, never their addresses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import Account
from ..base import Failure, account


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
