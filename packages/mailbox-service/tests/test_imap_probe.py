"""Reading an IMAP server's capabilities without logging in."""

from __future__ import annotations

import ssl
from typing import Any

import pytest

from benethos_mailbox_service.data.models import Security, ServerProtocol
from benethos_mailbox_service.data.providers import probe_server
from benethos_mailbox_service.data.providers.imap import probe
from benethos_mailbox_service.data.providers.protocols.imap import (
    ImapServer,
    ImapSession,
)
from benethos_mailbox_service.errors import (
    BadRequestError,
    NotSupportedError,
    ProviderError,
    ProviderUnavailableError,
)

from .imap_fake import FakeMailBox


def factory(mailbox_factory: Any) -> Any:
    return lambda server: ImapSession(server, client_factory=mailbox_factory)


async def test_probe_reads_capabilities_and_sends_no_credential() -> None:
    box = FakeMailBox()
    box.announced = ["IMAP4rev1", "IDLE", "AUTH=PLAIN"]
    caps = await probe("imap.example.com", 143, "starttls", factory(box))
    assert caps == frozenset({"IMAP4REV1", "IDLE", "AUTH=PLAIN"})
    assert box.calls == [
        ("connect", "imap.example.com", 143, "starttls"),
        ("logout",),
    ]
    assert box.logins == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OSError("connection refused"), ProviderUnavailableError),
        (TimeoutError(), ProviderUnavailableError),
        (ssl.SSLCertVerificationError("bad certificate"), ProviderError),
    ],
)
async def test_probe_errors_are_translated(
    error: Exception, expected: type[Exception]
) -> None:
    def failing(server: ImapServer, timeout: float) -> Any:
        raise error

    with pytest.raises(expected):
        await probe("imap.example.com", 993, "tls", factory(failing))


async def test_probe_refuses_plain_text() -> None:
    with pytest.raises(BadRequestError):
        await probe("imap.example.com", 143, "none", factory(FakeMailBox()))


async def test_registry_probes_only_imap() -> None:
    with pytest.raises(NotSupportedError):
        await probe_server(ServerProtocol.SMTP, "smtp.example.com", 465, Security.TLS)
