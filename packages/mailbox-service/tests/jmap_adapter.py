"""The JMAP adapter on the fake JMAP server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import SecretStr

from benethos_mailbox_service.data.protocols import ServerClient
from benethos_mailbox_service.data.providers.jmap import JmapProvider

from .jmap_fake import HOST, PASSWORD, TOKEN, USER, FakeJmap

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def adapter(server: FakeJmap, **settings: Any) -> JmapProvider:
    secrets = {"password": PASSWORD, "token": TOKEN}
    return JmapProvider(
        {"host": HOST, "username": USER, **settings},
        lambda field: SecretStr(secrets[field]),
        http=ServerClient(transport=httpx.MockTransport(server)),
        now=lambda: NOW,
    )
