"""The state of the service, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable

from ..fake_api import FakeApi


async def test_get_status(make_client: Callable) -> None:
    api = FakeApi(
        {
            "worker": {
                "interval": 300,
                "push": True,
                "last_pass_at": None,
                "watchers": 10,
                "watching": 2,
            },
            "accounts": [
                {
                    "id": "acc_1",
                    "email": "me@example.com",
                    "provider": "imap",
                    "status": "connected",
                    "synced": True,
                    "watching": True,
                    "last_sync_at": "2026-10-09T12:00:00Z",
                    "last_error": "503 from server",
                    "last_error_at": "2026-10-09T12:05:00Z",
                    "attention": True,
                }
            ],
        }
    )
    found = await make_client(api).get_status()
    assert api.call() == ("GET", "/v1/status", {}, None)
    assert found.worker is not None and found.worker.interval == 300.0
    [account] = found.accounts
    assert account.attention and account.last_error == "503 from server"


async def test_a_worker_switched_off(make_client: Callable) -> None:
    found = await make_client(FakeApi({"worker": None, "accounts": []})).get_status()
    assert found.worker is None and found.accounts == ()
