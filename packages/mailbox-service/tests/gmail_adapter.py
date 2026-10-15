"""The Gmail adapter on the fake Gmail API."""

from __future__ import annotations

import httpx

from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.providers.gmail import GmailProvider

from .gmail_fake import TOKEN, FakeGmail
from .oauth_fake import Tokens


def adapter(gmail: FakeGmail, tokens: Tokens | None = None) -> GmailProvider:
    return GmailProvider(
        tokens or Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(gmail))
    )
