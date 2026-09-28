"""Webhooks and their posts (docs/LOGGING.md 5.7). A webhook is named by
its id and the host it posts to, never by its URL: a URL may carry a key
in its query."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ..base import Activity, Failure, plural


@dataclass(frozen=True, kw_only=True)
class WebhookCreated(Activity):
    webhook_id: str
    host: str
    events: tuple[str, ...]
    # None: every account the creator may read.
    accounts: int | None

    def says(self) -> str:
        accounts = (
            "every account"
            if self.accounts is None
            else plural(self.accounts, "account")
        )
        return (
            f"created webhook {self.webhook_id} to {self.host} for "
            f"{', '.join(self.events)} of {accounts}"
        )


@dataclass(frozen=True, kw_only=True)
class WebhookRemoved(Activity):
    webhook_id: str
    host: str

    def says(self) -> str:
        return f"removed webhook {self.webhook_id} to {self.host}"


@dataclass(frozen=True, kw_only=True)
class PostFailed(Activity):
    """One post the receiver did not take. It is tried again."""

    level: ClassVar[int] = logging.WARNING

    webhook_id: str
    attempt: int
    attempts: int
    reason: str

    def says(self) -> str:
        return (
            f"could not post for webhook {self.webhook_id}, attempt "
            f"{self.attempt} of {self.attempts}"
        )

    def why(self) -> str:
        return self.reason


@dataclass(frozen=True, kw_only=True)
class GaveUp(Activity):
    level: ClassVar[int] = logging.WARNING

    webhook_id: str
    changes: int
    attempts: int
    reason: str

    def says(self) -> str:
        return (
            f"gave up on {plural(self.changes, 'change')} for webhook "
            f"{self.webhook_id} after {self.attempts} attempts"
        )

    def why(self) -> str:
        return self.reason


@dataclass(frozen=True, kw_only=True)
class DeliversAgain(Activity):
    """A post went through after posts had failed."""

    webhook_id: str

    def says(self) -> str:
        return f"posted for webhook {self.webhook_id} again"


@dataclass(frozen=True, kw_only=True)
class WebhookFailed(Failure):
    webhook_id: str

    def says(self) -> str:
        return f"could not post for webhook {self.webhook_id}"
