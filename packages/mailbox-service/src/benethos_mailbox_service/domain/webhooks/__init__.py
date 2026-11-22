"""Webhooks: register, list, change and remove them (``WebhookService``), and
post the changes of the feed to them (``WebhookDispatcher``)
(CONCEPT 6.5).
"""

from __future__ import annotations

from .delivery import Retries, WebhookDispatcher
from .service import WebhookCounts, WebhookService

__all__ = [
    "Retries",
    "WebhookCounts",
    "WebhookDispatcher",
    "WebhookService",
]
