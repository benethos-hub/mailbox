"""Folder ids a caller made up. An id is not signed, so anyone can build
one: what it names never reaches a command of the mail server, and one
the account lacks is missing on every provider."""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.common import opaque
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Folder, Grant
from benethos_mailbox_service.domain.rights.access import Access

from ...conftest import bearer_for, memory_of
from ...imap_fake import FakeMailBox

# A name that would end SELECT and start a command of the caller's choosing.
FORGED = opaque.encode("f_", ['INBOX"\r\nZ99 DELETE "Important'])
INVOICES = Folder(id="f_inv", name="Invoices")


@pytest.mark.parametrize("path", ["messages", "threads"])
def test_a_forged_folder_id_never_reaches_the_server(
    path: str, imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    grant = Grant(accounts=[imap_account_id], allow=["mail.read"])
    client = TestClient(
        create_app(Settings(storage="memory"), imap_services),
        headers=bearer_for(imap_services, grant),
    )
    answer = client.get(
        f"/v1/accounts/{imap_account_id}/{path}", params={"folder": FORGED}
    )
    assert answer.status_code == 404
    sent = [a for c in imap_server.calls for a in c[1:] if isinstance(a, str)]
    assert not [a for a in sent if "\r" in a or "\n" in a]


def test_a_folder_the_account_lacks_is_missing_before_any_message_is_asked(
    client: TestClient,
    services: Services,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = memory_of(services, account_id)
    memory.folders.append(INVOICES)
    real = memory.list_messages
    asked: list[None] = []

    async def counted(*args: Any, **kwargs: Any) -> Any:
        asked.append(None)
        return await real(*args, **kwargs)

    monkeypatch.setattr(memory, "list_messages", counted)
    base = f"/v1/accounts/{account_id}/messages"
    answer = client.get(base, params={"folder": "f_made_up"})
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "not_found"
    assert asked == []
    assert client.get(base, params={"folder": INVOICES.id}).status_code == 200
    assert len(asked) == 1


def test_a_list_of_a_folder_asks_for_the_folders_once(
    services: Services, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory = memory_of(services, account_id)
    memory.folders.append(INVOICES)
    real = memory.list_folders
    asked: list[None] = []

    async def counted() -> list[Folder]:
        asked.append(None)
        return await real()

    monkeypatch.setattr(memory, "list_folders", counted)
    grant = Grant(accounts=[account_id], allow=["list_messages"])

    async def listed() -> int:
        page = await services.mailbox.list_messages(
            Access("u", "u", [grant]),
            account_id,
            folder_id=INVOICES.id,
            limit=10,
            cursor=None,
        )
        return len(page.items)

    assert anyio.run(listed) == 0
    assert len(asked) == 1
