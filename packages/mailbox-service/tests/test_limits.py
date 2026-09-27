"""The size of a request body: refused with 413 before it is read whole."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.main import Services
from benethos_mailbox_service.web import limits

from .ui_helpers import csrf_of

LIMIT = 4096


@pytest.fixture(autouse=True)
def small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Read when the app builds its middleware, at the first request.
    monkeypatch.setattr(limits, "MAX_BODY", LIMIT)


def test_a_declared_body_above_the_limit_is_refused(
    client: TestClient, account_id: str, services: Services
) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "you@example.com"}], "text": "x" * LIMIT},
    )
    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "payload_too_large"
    assert services.adapters.get(account_id).outbox == []  # type: ignore[attr-defined]


def test_a_chunked_body_is_cut_off_at_the_limit(
    client: TestClient, account_id: str
) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"to": [{"email": "you@example.com"}], "text": "'
        for _ in range(8):
            yield b"x" * 1024
        yield b'"}'

    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "payload_too_large"


def test_a_body_within_the_limit_passes(client: TestClient, account_id: str) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "you@example.com"}], "text": "Hallo"},
    )
    assert answer.status_code == 200


def test_an_upload_above_the_limit_is_a_page(ui: TestClient, account_id: str) -> None:
    form = ui.get(f"/ui/accounts/{account_id}/compose").text
    answer = ui.post(
        f"/ui/accounts/{account_id}/compose",
        data={"csrf_token": csrf_of(form), "to": "bob@example.org", "do": "send"},
        files=[("attachments", ("big.bin", b"x" * LIMIT, "application/octet-stream"))],
    )
    assert answer.status_code == 413
    assert "larger than" in answer.text
    assert answer.headers["content-type"].startswith("text/html")
