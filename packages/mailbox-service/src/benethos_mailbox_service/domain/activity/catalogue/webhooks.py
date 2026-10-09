"""Webhooks and their posts (docs/LOGGING.md 5.7). A webhook is named by
its id and the host it posts to, never by its URL: a URL may carry a key
in its query."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....common.text import plural
from ..base import Activity, Failure


@dataclass(frozen=True, kw_only=True)
class WebhookCreated(Activity):
    name: ClassVar[str] = "created"
    audited: ClassVar[bool] = True

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

    def touched(self) -> str | None:
        return self.webhook_id


@dataclass(frozen=True, kw_only=True)
class WebhookChanged(Activity):
    name: ClassVar[str] = "changed"
    audited: ClassVar[bool] = True

    webhook_id: str
    # The host it posts to now.
    host: str
    # What changed: url, events, accounts.
    changed: tuple[str, ...]

    def says(self) -> str:
        return (
            f"changed the {', '.join(self.changed)} of webhook {self.webhook_id}"
            f", posting to {self.host}"
        )

    def touched(self) -> str | None:
        return self.webhook_id


@dataclass(frozen=True, kw_only=True)
class SecretRenewed(Activity):
    name: ClassVar[str] = "secret_renewed"
    audited: ClassVar[bool] = True

    webhook_id: str
    host: str

    def says(self) -> str:
        return (
            f"gave webhook {self.webhook_id} to {self.host} a new signing secret,"
            " the one before stops at once"
        )

    def touched(self) -> str | None:
        return self.webhook_id


@dataclass(frozen=True, kw_only=True)
class WebhookRemoved(Activity):
    name: ClassVar[str] = "removed"
    audited: ClassVar[bool] = True

    webhook_id: str
    host: str

    def says(self) -> str:
        return f"removed webhook {self.webhook_id} to {self.host}"

    def touched(self) -> str | None:
        return self.webhook_id


@dataclass(frozen=True, kw_only=True)
class PostFailed(Activity):
    """One post the receiver did not take. It is tried again."""

    name: ClassVar[str] = "post_failed"
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
    name: ClassVar[str] = "gave_up"
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

    name: ClassVar[str] = "delivers_again"

    webhook_id: str

    def says(self) -> str:
        return f"posted for webhook {self.webhook_id} again"


@dataclass(frozen=True, kw_only=True)
class WebhookFailed(Failure):
    name: ClassVar[str] = "failed"

    webhook_id: str

    def says(self) -> str:
        return f"could not post for webhook {self.webhook_id}"
