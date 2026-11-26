"""The webhooks while the service's database fails: no webhook is taken
for removed, the round fails, and the next round posts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.errors import StorageUnavailableError

from ..conftest import Receiver
from ..webhook_helpers import hook, mark_read

pytestmark = pytest.mark.usefixtures("master_key")


async def test_a_database_away_fails_the_round_and_the_next_one_posts(
    client: TestClient,
    services: Services,
    account_id: str,
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook(client)
    mark_read(client, account_id, "m0")
    repository = services.repositories.webhooks

    def away(*args: object, **kwargs: object) -> None:
        raise StorageUnavailableError(4, "AdminShutdown (57P01)")

    with monkeypatch.context() as patched:
        patched.setattr(repository, "get", away)
        with pytest.raises(StorageUnavailableError):
            await services.deliveries.deliver_due()
    assert receiver.posts == []
    await services.deliveries.deliver_due()
    assert len(receiver.posts) == 1
