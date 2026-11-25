"""The outbox with a clock of its own, for the tests of its runner: the
services, an account of the memory adapter and a user with every right."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Message,
    OutboxJob,
    OutgoingMessage,
    ProviderType,
    Recipient,
    SentMessage,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    build_provider,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.domain.mailbox import OutboxRunner
from benethos_mailbox_service.domain.rights import Access, permissions
from benethos_mailbox_service.errors import (
    MailboxServiceError,
)

from ....clocks import Clock
from ....conftest import ADMIN, CHEAP, create_account, memory_of

Send = Callable[[bytes, str, list[str]], Awaitable[SentMessage]]


@dataclass
class Outbox:
    services: Services
    clock: Clock
    account_id: str
    access: Access
    user_id: str

    @property
    def runner(self) -> OutboxRunner:
        assert self.services.outbox is not None
        return self.services.outbox

    def queue(self, account_id: str | None = None, **when: float) -> OutboxJob:
        send_at = self.clock.now + timedelta(**when) if when else None
        return asyncio.run(
            self.services.mailbox.outgoing.queue_message(
                self.access,
                account_id or self.account_id,
                OutgoingMessage(to=[Recipient(email="bob@example.com")], text="Hi."),
                send_at,
            )
        )

    def round(self) -> None:
        asyncio.run(self.runner.send_due())

    def job(self, job_id: str) -> OutboxJob:
        return self.services.mailbox.outgoing.outbox.jobs.get(job_id)

    def sent(self, account_id: str | None = None) -> list[bytes]:
        return [raw for _, _, raw in self.memory(account_id).outbox]

    def memory(self, account_id: str | None = None) -> MemoryProvider:
        return memory_of(self.services, account_id or self.account_id)

    def drafts(self) -> list[str]:
        page = asyncio.run(
            self.services.mailbox.outgoing.list_drafts(
                ADMIN, self.account_id, limit=10, cursor=None
            )
        )
        return [item.id for item in page.items]

    def outcomes(self) -> list[tuple[str, str | None]]:
        page = self.services.mailbox.outgoing.list_sends(
            ADMIN, self.account_id, limit=20, cursor=None
        )
        return sorted((r.outcome, r.error) for r in page.items)

    def failing(self, *errors: MailboxServiceError | None) -> None:
        """The provider's sends raise ``errors`` in turn, then send."""
        provider = self.memory()
        real: Send = provider.send
        left = list(errors)

        async def send(raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
            error = left.pop(0) if left else None
            if error is not None:
                raise error
            return await real(raw, sender, recipients)

        provider.send = send  # type: ignore[method-assign]


def build(messages: list[Message], hours: int = 48) -> Outbox:
    clock = Clock()

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> Reads:
        if kind is ProviderType.MEMORY:
            return MemoryProvider(messages=list(messages))
        return build_provider(kind, settings, credentials)

    services = build_services(
        Settings(storage="memory", outbox_retry_hours=hours),
        provider_factory=factory,
        password_hasher=CHEAP,
        clock=clock,
    )
    account = create_account(services.accounts, ProviderType.MEMORY, "me@example.com")
    user = services.users.create_user(
        ADMIN, "sender", [], [], service=[permissions.ADMIN]
    )
    access = services.auth.access_of(user.id)
    assert access is not None
    return Outbox(services, clock, account.id, access, user.id)
