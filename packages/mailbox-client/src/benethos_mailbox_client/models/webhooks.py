"""Webhooks and their signing secrets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .secrets import Secret


@dataclass(frozen=True)
class Webhook:
    """A URL that hears of events. ``accounts`` None: every account its
    owner may read, accounts added later included."""

    id: str
    url: str
    events: tuple[str, ...]
    accounts: tuple[str, ...] | None
    user_id: str
    created_at: datetime
    last_delivery_at: datetime | None
    # Why the last post failed, if it did.
    last_error: str | None


@dataclass(frozen=True)
class WebhookSecret:
    """A webhook's new signing secret, shown this once. The one before
    stops at once."""

    webhook_id: str
    secret: Secret
