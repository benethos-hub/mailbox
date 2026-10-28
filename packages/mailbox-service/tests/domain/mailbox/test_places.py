"""Where an account keeps no index, a change under grants that name
folders asks the provider for the folders of each message, read without
its content where the provider can (``Places``)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Folder, Grant, Message

from ...conftest import bearer_for, memory_of

INVOICES = Folder(id="f_inv", name="Invoices")


@pytest.mark.parametrize("places", [True, False])
def test_a_batch_under_folder_grants_reads_only_the_folders(
    app_client: TestClient,
    services: Services,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
    places: bool,
) -> None:
    memory = memory_of(services, account_id)
    memory.folders.append(INVOICES)
    memory.messages = [
        m.model_copy(update={"folder_ids": [INVOICES.id if m.id != "m3" else "inbox"]})
        for m in memory.messages
    ]
    light: list[list[str]] = []
    whole: list[str] = []
    real = memory.get_message

    async def get_message(message_id: str) -> Message:
        whole.append(message_id)
        return await real(message_id)

    async def folders_of(ids: list[str]) -> dict[str, list[str]]:
        light.append(ids)
        return {m.id: list(m.folder_ids) for m in memory.messages if m.id in ids}

    monkeypatch.setattr(memory, "get_message", get_message)
    if places:
        monkeypatch.setattr(memory, "folders_of", folders_of, raising=False)
    grant = Grant(accounts=[account_id], allow=["mail.write"], folders=["Invoices"])
    writer = TestClient(app_client.app, headers=bearer_for(services, grant))
    answer: Any = writer.post(
        f"/v1/accounts/{account_id}/messages/batch",
        json={
            "ids": ["m0", "m1", "m3"],
            "action": "update",
            "changes": {"unread": True},
        },
    ).json()
    outcome = {r["id"]: r.get("ok", False) for r in answer["results"]}
    assert outcome == {"m0": True, "m1": True, "m3": False}
    if places:
        assert (len(light), whole) == (3, [])
    else:
        assert (light, len(whole)) == ([], 3)
