"""The Microsoft adapter on the fake of Graph."""

from __future__ import annotations

import httpx

from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.providers import (
    TokenSource,
)
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider

from .graph_fake import TOKEN, FakeGraph
from .oauth_fake import Tokens


def adapter(graph: FakeGraph, tokens: TokenSource | None = None) -> MicrosoftProvider:
    return MicrosoftProvider(
        tokens or Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(graph))
    )
