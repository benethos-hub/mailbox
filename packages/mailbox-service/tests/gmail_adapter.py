"""The Gmail adapter on the fake Gmail API."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

import httpx

from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.providers.gmail import GmailProvider

from .gmail_fake import TOKEN, FakeGmail
from .oauth_fake import Tokens


def adapter(
    gmail: FakeGmail,
    tokens: Tokens | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = utc_now,
) -> GmailProvider:
    return GmailProvider(
        tokens or Tokens(TOKEN),
        ApiClient(transport=httpx.MockTransport(gmail)),
        clock=clock,
        now=now,
    )
