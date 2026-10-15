"""A service with one account whose message carries a PDF, a user whose
token may share it, and a clock the test moves: what the tests of links
to attachments share."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Address,
    Attachment,
    Grant,
    Message,
    ProviderType,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider

from ...clocks import Clock
from ...conftest import ADMIN, CHEAP, create_account

PDF = b"%PDF-1.7 a report"
SHARE = ["mail.read", "mail.share"]


@dataclass
class Linked:
    """The service, a client without credentials, the account, and the user
    whose token shares."""

    services: Services
    client: TestClient
    clock: Clock
    account_id: str
    user_id: str
    token_id: str
    bearer: dict[str, str]

    def share_url(self, message_id: str = "m0", attachment_id: str = "att_0") -> str:
        return (
            f"/v1/accounts/{self.account_id}/messages/{message_id}"
            f"/attachments/{attachment_id}/links"
        )

    def share(self, **body: Any) -> httpx.Response:
        """``share_attachment`` with the user's token, ``body`` its JSON."""
        return self.client.post(
            self.share_url(), headers=self.bearer, json=body or None
        )

    def secret(self, **body: Any) -> str:
        """The secret of a new link."""
        answer = self.share(**body)
        assert answer.status_code == 201, answer.text
        return str(answer.json()["url"]).rpartition("/")[2]

    def fetch(self, secret: str) -> httpx.Response:
        return self.client.get(f"/v1/links/{secret}")

    def grant(self, *grants: Grant) -> None:
        """The user's grants, from now on."""
        self.services.users.update_user(ADMIN, self.user_id, grants=list(grants))


def message() -> Message:
    return Message(
        id="m0",
        folder_ids=["inbox"],
        subject="Report",
        sender=Address(email="alice@example.com"),
        date=datetime(2026, 9, 1, tzinfo=UTC),
        attachments=[
            Attachment(
                id="att_0",
                filename="Report 7.pdf",
                content_type="application/pdf",
                size=len(PDF),
            )
        ],
    )


def linked(*allow: str, **settings: Any) -> Linked:
    """The service with ``settings``, and a user whose grant on the account
    allows ``allow``, by default reading and sharing."""
    clock = Clock()

    def factory(kind: ProviderType, _: ProviderSettings, __: CredentialReader) -> Reads:
        provider = MemoryProvider(messages=[message()])
        provider.attachment_data[("m0", "att_0")] = PDF
        return provider

    chosen = Settings(storage="memory", **settings)
    built = build_services(
        chosen, provider_factory=factory, password_hasher=CHEAP, clock=clock
    )
    account_id = create_account(
        built.accounts, ProviderType.MEMORY, "me@example.com"
    ).id
    user = built.users.create_user(
        ADMIN,
        "sharer",
        [],
        [Grant(accounts=[account_id], allow=list(allow or SHARE))],
    )
    issued = built.auth.issue_token(user.id, "mcp")
    return Linked(
        services=built,
        client=TestClient(create_app(chosen, built)),
        clock=clock,
        account_id=account_id,
        user_id=user.id,
        token_id=issued.token.id,
        bearer={"Authorization": f"Bearer {issued.plain}"},
    )
