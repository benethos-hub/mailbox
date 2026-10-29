"""Fixtures the tests of the webhooks share."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryWebhookRepository,
    SqliteWebhookRepository,
    WebhookRepository,
)


@pytest.fixture(params=["memory", "sqlite"])
def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[WebhookRepository]:
    if request.param == "memory":
        yield InMemoryWebhookRepository()
        return
    db = Database(tmp_path / "hooks.db")
    # The sealed secret names a data key that must exist.
    db.execute(
        "INSERT INTO keys (key_id, nonce, ciphertext) VALUES ('k1', x'00', x'00')"
    )
    yield SqliteWebhookRepository(db)
    db.close()


@pytest.fixture
def ready(services: Services) -> Services:
    """Services whose vault can seal a secret."""
    services.vault.initialize()
    return services
