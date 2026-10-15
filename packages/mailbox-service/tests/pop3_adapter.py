"""The POP3 adapter on the fake POP3 server, and a fake SMTP server for
sending."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.data.protocols.smtp import SmtpSession
from benethos_mailbox_service.data.providers import Timing
from benethos_mailbox_service.data.providers.pop3 import Pop3Provider, mappers

from .imap_fake import make_message
from .pop3_fake import FakePop3Server
from .smtp_fake import FakeSmtpServer

SETTINGS = {"host": "pop.example.com", "username": "me@example.com"}
INBOX = mappers.folder_id()


def filled_server() -> FakePop3Server:
    """Five mails, one a day from the first of September."""
    box = FakePop3Server()
    for n in range(1, 6):
        box.add(
            f"uid-{n}",
            make_message(f"Mail {n}", date=datetime(2026, 9, n, 10, 0, tzinfo=UTC)),
        )
    return box


def provider(
    box: FakePop3Server, smtp: FakeSmtpServer | None = None, **overrides: Any
) -> Pop3Provider:
    def credentials(field: str) -> SecretStr:
        assert field == "password"
        return SecretStr("secret")

    settings = {**SETTINGS, **overrides}
    if smtp is not None:
        settings["smtp_host"] = "smtp.example.com"
    return Pop3Provider(
        settings,
        credentials,
        session_factory=lambda s: Pop3Session(s, connection_factory=box),
        timing=Timing(sleep=lambda seconds: None),
        smtp_factory=lambda s: SmtpSession(s, connection_factory=smtp),
    )


def subjects(items: list[Any]) -> list[str | None]:
    return [item.subject for item in items]


def pop3_protocol_server() -> Any:
    from benethos_mailbox_service.data.protocols import Server

    return Server(host="pop.example.com", port=995, security="tls")
