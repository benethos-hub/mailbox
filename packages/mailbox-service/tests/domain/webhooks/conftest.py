"""Fixtures the tests of the webhooks share."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.storage import (
    Repositories,
    WebhookRepository,
    WrappedKey,
)


@pytest.fixture
def store(repositories: Repositories) -> WebhookRepository:
    # The sealed secret names a data key that must exist.
    repositories.keys.add(WrappedKey("k1", b"\x00", b"\x00"))
    return repositories.webhooks


@pytest.fixture
def ready(services: Services) -> Services:
    """Services whose vault can seal a secret."""
    services.vault.initialize()
    return services
