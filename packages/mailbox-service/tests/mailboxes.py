"""Every kind of mailbox through its fake, built alike: the adapter on its
own, and an account of it in the real services. The conformance suites
run the same expectations over all of them (docs/UNIFORM.md section 7).

Each mailbox has an inbox, a sent folder, drafts and a trash where its
provider keeps them, and IMAP and POP3 send through a fake SMTP server.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.mail import convert, parse
from benethos_mailbox_service.data.models import (
    Folder,
    FolderRole,
    Message,
    ProviderType,
)
from benethos_mailbox_service.data.protocols.http import ApiClient, ServerClient
from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.data.protocols.smtp import SmtpSession
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    TokenSource,
    sign_in,
)
from benethos_mailbox_service.data.providers.gmail import GmailProvider
from benethos_mailbox_service.data.providers.imap import ImapProvider
from benethos_mailbox_service.data.providers.jmap import JmapProvider
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider
from benethos_mailbox_service.data.providers.pop3 import Pop3Provider
from benethos_mailbox_service.data.secrets import cipher, encode_recovery

from .conftest import create_account
from .gmail_fake import TOKEN as GMAIL_TOKEN
from .gmail_fake import FakeGmail
from .graph_fake import TOKEN as GRAPH_TOKEN
from .graph_fake import FakeGraph
from .imap_fake import FakeFolder, FakeMailBox
from .jmap_fake import HOST, PASSWORD, USER, FakeJmap
from .pop3_fake import FakePop3Server
from .smtp_fake import FakeSmtpServer

KINDS = ("memory", "imap", "pop3", "jmap", "gmail", "microsoft")
ADDRESS = "me@example.org"
SMTP = {"smtp_host": "smtp.example.com", "smtp_port": "587"}


@dataclass
class Box:
    """One mailbox: its fake, a way to make an adapter on it, and a way to
    put a mail into its inbox as if it arrived."""

    kind: str
    provider: ProviderType
    fake: Any
    make: Callable[[], Reads]
    put: Callable[[bytes], None]
    settings: dict[str, str] = field(default_factory=dict)
    smtp: FakeSmtpServer | None = None


def mail(subject: str, text: str = "Hello", file: bytes | None = None) -> bytes:
    """A mail to the mailbox, with a file where ``file`` is given."""
    found = EmailMessage()
    found["From"] = "Alice <alice@example.com>"
    found["To"] = ADDRESS
    found["Subject"] = subject
    found["Date"] = "Tue, 01 Sep 2026 10:00:00 +0000"
    found["Message-ID"] = f"<{subject.replace(' ', '.')}@example.com>"
    found.set_content(text)
    if file is not None:
        found.add_attachment(file, "application", "pdf", filename="offer.pdf")
    return found.as_bytes()


def box(kind: str, smtp: bool = True) -> Box:
    """A mailbox of ``kind``. Without ``smtp``, IMAP and POP3 name no SMTP
    server."""
    found = _BOXES[kind]()
    if not smtp:
        for name in SMTP:
            found.settings.pop(name, None)
    return found


# --- each kind ------------------------------------------------------------------------


class _Tokens:
    """A token source that always has ``value``."""

    def __init__(self, value: str) -> None:
        self.value = value

    async def access_token(self) -> SecretStr:
        return SecretStr(self.value)

    def reject(self) -> None:
        pass

    def forget_refusal(self) -> None:
        pass


def _memory() -> Box:
    adapter = MemoryProvider(
        folders=[
            Folder(id="inbox", name="Inbox", role=FolderRole.INBOX),
            Folder(id="sent", name="Sent", role=FolderRole.SENT),
            Folder(id="drafts", name="Drafts", role=FolderRole.DRAFTS),
            Folder(id="trash", name="Trash", role=FolderRole.TRASH),
        ]
    )
    numbers = itertools.count(1)

    def put(raw: bytes) -> None:
        parsed = parse.ParsedMessage(raw)
        message_id = f"m{next(numbers)}"
        adapter.messages.append(
            Message.model_validate(
                {
                    "id": message_id,
                    "folder_ids": ["inbox"],
                    "unread": True,
                    **convert.summary_fields(parsed),
                    **convert.message_fields(parsed),
                }
            )
        )
        adapter.raws[message_id] = raw
        for index, part in enumerate(parsed.attachments):
            key = (message_id, convert.attachment_id(index))
            adapter.attachment_data[key] = part.payload

    return Box("memory", ProviderType.MEMORY, adapter, lambda: adapter, put)


def _imap() -> Box:
    server = FakeMailBox()
    server.folders = {
        "INBOX": FakeFolder(uidvalidity=7),
        "Sent": FakeFolder(flags=("\\HasNoChildren", "\\Sent")),
        "Drafts": FakeFolder(flags=("\\HasNoChildren", "\\Drafts")),
        "Trash": FakeFolder(flags=("\\HasNoChildren", "\\Trash")),
    }
    smtp = FakeSmtpServer()
    settings = {"host": "imap.example.com", "username": ADDRESS, **SMTP}
    uids = itertools.count(1)

    def make() -> Reads:
        return ImapProvider(
            settings,
            lambda field: SecretStr("secret"),
            session_factory=lambda s: ImapSession(s, client_factory=server),
            smtp_factory=lambda s: SmtpSession(s, connection_factory=smtp),
            sleep=lambda seconds: None,
        )

    return Box(
        "imap",
        ProviderType.IMAP,
        server,
        make,
        lambda raw: server.add("INBOX", next(uids), raw),
        settings,
        smtp,
    )


def _pop3() -> Box:
    server = FakePop3Server()
    smtp = FakeSmtpServer()
    settings = {"host": "pop.example.com", "username": ADDRESS, **SMTP}
    uids = itertools.count(1)

    def make() -> Reads:
        return Pop3Provider(
            settings,
            lambda field: SecretStr("secret"),
            session_factory=lambda s: Pop3Session(s, connection_factory=server),
            smtp_factory=lambda s: SmtpSession(s, connection_factory=smtp),
            sleep=lambda seconds: None,
        )

    return Box(
        "pop3",
        ProviderType.POP3,
        server,
        make,
        lambda raw: server.add(f"uid-{next(uids)}", raw),
        settings,
        smtp,
    )


def _jmap() -> Box:
    server = FakeJmap()
    settings = {"host": HOST, "username": USER}

    def make() -> Reads:
        return JmapProvider(
            settings,
            lambda field: SecretStr(PASSWORD),
            http=ServerClient(transport=httpx.MockTransport(server)),
        )

    return Box(
        "jmap",
        ProviderType.JMAP,
        server,
        make,
        lambda raw: server.add_email(raw) and None,
        settings,
    )


def _gmail() -> Box:
    server = FakeGmail()

    def make() -> Reads:
        return GmailProvider(
            _Tokens(GMAIL_TOKEN), ApiClient(transport=httpx.MockTransport(server))
        )

    return Box(
        "gmail",
        ProviderType.GMAIL,
        server,
        make,
        lambda raw: server.add_message(raw=raw) and None,
    )


def _microsoft() -> Box:
    server = FakeGraph()

    def put(raw: bytes) -> None:
        parsed = parse.ParsedMessage(raw)
        server.add_message(
            raw=raw,
            subject=parsed.subject,
            hasAttachments=bool(parsed.attachments),
            internetMessageId=parsed.message_id,
        )

    def make() -> Reads:
        return MicrosoftProvider(
            _Tokens(GRAPH_TOKEN), ApiClient(transport=httpx.MockTransport(server))
        )

    return Box("microsoft", ProviderType.MICROSOFT, server, make, put)


_BOXES: dict[str, Callable[[], Box]] = {
    "memory": _memory,
    "imap": _imap,
    "pop3": _pop3,
    "jmap": _jmap,
    "gmail": _gmail,
    "microsoft": _microsoft,
}


# --- an account of it in the real services --------------------------------------------


def services_of(found: Box, monkeypatch: pytest.MonkeyPatch) -> tuple[Services, str]:
    """The real services with one account of ``found``, and its id. The
    adapter of every account is one on the fake."""
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType,
        settings: ProviderSettings,
        credentials: CredentialReader,
        /,
        *,
        tokens: TokenSource | None = None,
    ) -> Reads:
        return found.make()

    oauth = {
        kind: OAuthClient(
            App(sign_in(kind), "client-1", SecretStr("secret")),
            ApiClient(transport=httpx.MockTransport(_token_endpoint)),
        )
        for kind in (ProviderType.GMAIL, ProviderType.MICROSOFT)
    }
    services = build_services(
        Settings(storage="memory"), provider_factory=factory, oauth_clients=oauth
    )
    services.vault.initialize()
    if found.provider in oauth:
        return services, _signed_in(services, found.provider)
    account = create_account(
        services.accounts,
        found.provider,
        ADDRESS,
        settings=found.settings,
        credentials={"password": SecretStr("secret")},
    )
    return services, account.id


def _token_endpoint(request: httpx.Request) -> httpx.Response:
    """Google's and Microsoft's token endpoints, Gmail's profile and Graph's
    ``/me``: each names the account's address."""
    host = urlsplit(str(request.url)).netloc
    if host == "graph.microsoft.com":
        return httpx.Response(200, json={"mail": ADDRESS})
    if host == "gmail.googleapis.com":
        return httpx.Response(200, json={"emailAddress": ADDRESS, "historyId": "1"})
    return httpx.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "expires_in": 3600,
        },
    )


def _signed_in(services: Services, kind: ProviderType) -> str:
    """An account of ``kind`` connected as a person would, through the
    sign-in the admin starts."""
    from .conftest import admin_bearer

    bearer = admin_bearer(services)["Authorization"].removeprefix("Bearer ")
    caller = services.auth.authenticate(bearer)
    url = services.oauth.start(caller, kind, "http://testserver/ui/oauth/callback")
    state = parse_qs(urlsplit(url).query)["state"][0]
    account = anyio.run(lambda: services.oauth.finish(caller, kind, state, "code"))
    return account.id
