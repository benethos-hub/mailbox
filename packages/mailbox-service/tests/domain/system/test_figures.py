"""The figures of the service for a monitor (`StatusService.figures`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant, ProviderType, Webhook
from benethos_mailbox_service.data.storage import Delivery, Sealed, WebhookRecord
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.errors import ForbiddenError

from ...conftest import create_account

AT = datetime(2026, 11, 22, 12, tzinfo=UTC)

MONITOR = Access("usr_m", "monitor", [], service=["metrics"])


def hook(n: int, user_id: str, last_error: str | None = None) -> WebhookRecord:
    return WebhookRecord(
        webhook=Webhook(
            id=f"whk_{n}",
            url=f"https://h.example.com/{n}",
            events=["message.created"],
            accounts=None,
            user_id=user_id,
            created_at=AT,
            last_error=last_error,
        ),
        secret=Sealed("k1", b"nonce", b"cipher"),
        delivery=Delivery(cursor=0),
    )


def test_the_figures_need_their_right(services: Services) -> None:
    reader = Access("usr_r", "reader", [Grant(accounts=["*"], allow=["accounts.read"])])
    with pytest.raises(ForbiddenError, match="missing right: get_metrics"):
        services.status.figures(reader)


def test_the_figures_hold_every_account_without_a_grant(
    services: Services, account_id: str
) -> None:
    other = create_account(services.accounts, ProviderType.MEMORY, "b@example.com")
    figures = services.status.figures(MONITOR)
    assert {h.account.id for h in figures.accounts} == {account_id, other.id}
    assert services.accounts.list(MONITOR) == []
    assert figures.worker is None  # switched off in the tests


def test_the_webhooks_of_every_user_are_counted(services: Services) -> None:
    store = services.repositories.webhooks
    store.add(hook(1, "usr_a"))
    store.add(hook(2, "usr_b", last_error="503 from receiver"))
    webhooks = services.status.figures(MONITOR).webhooks
    assert (webhooks.total, webhooks.failing) == (2, 1)


def test_the_status_and_the_figures_are_two_rights(services: Services) -> None:
    status = Access("usr_s", "status", [Grant(accounts=["*"], allow=["accounts.read"])])
    services.status.status(status)
    with pytest.raises(ForbiddenError):
        services.status.figures(status)
    with pytest.raises(ForbiddenError):
        services.status.status(MONITOR)
