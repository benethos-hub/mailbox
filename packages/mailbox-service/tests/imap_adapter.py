"""The IMAP adapter on the fake of IMAPClient, and on a fake SMTP server
for sending."""

from __future__ import annotations

from typing import Any

import anyio
from pydantic import SecretStr

from benethos_mailbox_service.data.protocols.imap import (
    ImapSession,
)
from benethos_mailbox_service.data.protocols.smtp import SmtpSession
from benethos_mailbox_service.data.providers import Timing
from benethos_mailbox_service.data.providers.guard import Pace
from benethos_mailbox_service.data.providers.imap import ImapProvider, mappers

from .clocks import Seconds
from .imap_fake import FakeMailBox
from .smtp_fake import FakeSmtpServer

SETTINGS = {"host": "imap.example.com", "username": "me@example.com"}


INBOX = mappers.folder_id("INBOX")


def provider(
    box: FakeMailBox,
    time: Seconds | None = None,
    pace: Pace | None = None,
    watchers: anyio.CapacityLimiter | None = None,
    **overrides: Any,
) -> ImapProvider:
    def credentials(field: str) -> SecretStr:
        assert field in ("password", "access_token")
        return SecretStr("secret")

    time = time or Seconds()
    return ImapProvider(
        {**SETTINGS, **overrides},
        credentials,
        session_factory=lambda s: ImapSession(
            s, client_factory=box, client_id=("benethos-mailbox-service", "1.0")
        ),
        timing=Timing(clock=time, sleep=time.sleep, jitter=lambda low, high: high),
        pace=pace,
        watchers=watchers,
    )


def sending(box: FakeMailBox, smtp: FakeSmtpServer, **settings: object) -> ImapProvider:
    """An adapter that sends through ``smtp``."""
    return ImapProvider(
        {
            "host": "imap.example.com",
            "username": "me@example.com",
            "smtp_host": "smtp.example.com",
            **settings,
        },
        lambda field: SecretStr("secret"),
        session_factory=lambda s: ImapSession(s, client_factory=box),
        smtp_factory=lambda server: SmtpSession(server, connection_factory=smtp),
    )
