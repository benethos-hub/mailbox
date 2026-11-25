"""Fixtures the tests of the storage share."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import Account, ProviderType
from benethos_mailbox_service.data.storage import (
    MessageIndexRepository,
    Repositories,
)

from .index_helpers import ACC


@pytest.fixture
def index(repositories: Repositories) -> MessageIndexRepository:
    for account_id in (ACC, "acc_2"):
        repositories.accounts.add(
            Account(id=account_id, provider=ProviderType.IMAP, email="a@example.com")
        )
    return repositories.index
