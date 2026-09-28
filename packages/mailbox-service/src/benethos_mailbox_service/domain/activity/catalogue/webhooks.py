"""Webhooks and their posts (docs/LOGGING.md 5.7). A webhook is named by
its id and the host it posts to, never by its URL: a URL may carry a key
in its query."""

from __future__ import annotations

from dataclasses import dataclass

from ..base import Failure


@dataclass(frozen=True, kw_only=True)
class WebhookFailed(Failure):
    webhook_id: str

    def says(self) -> str:
        return f"could not post for webhook {self.webhook_id}"
