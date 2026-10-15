"""Webhooks through the API: one made, a message read so that it fires."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

URL = "https://hooks.example.com/mail"


def hook(client: TestClient, **fields: Any) -> dict[str, Any]:
    answer = client.post("/v1/webhooks", json={"url": URL, **fields})
    assert answer.status_code == 201, answer.text
    created: dict[str, Any] = answer.json()
    return created


def mark_read(client: TestClient, account_id: str, message_id: str) -> None:
    answer = client.patch(
        f"/v1/accounts/{account_id}/messages/{message_id}", json={"unread": False}
    )
    assert answer.status_code == 200
