"""Discovery from an address, and the sign-in with a code, the same for
both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Hint, MailServer, SourceReport

from ..fake_api import ACCOUNT, FakeApi

FOUND = {
    "email": "me@example.com",
    "domain": "example.com",
    "candidates": [
        {
            "provider": "imap",
            "name": "Example Mail",
            "credential": "password",
            "servers": [
                {
                    "protocol": "imap",
                    "host": "imap.example.com",
                    "port": 993,
                    "security": "tls",
                    "reachable": True,
                    "capabilities": ["IDLE"],
                }
            ],
            "hints": [{"text": "Use an app password", "url": "https://x.example"}],
            "source": "autoconfig",
            "confirmed": True,
            "settings": {"host": "imap.example.com", "port": 993},
        }
    ],
    "sources": [{"source": "mx", "outcome": "nothing"}],
}


async def test_discover_account(make_client: Callable) -> None:
    api = FakeApi(FOUND)
    found = await make_client(api).discover_account("me@example.com")
    assert api.call() == ("POST", "/v1/discovery", {}, {"email": "me@example.com"})
    [candidate] = found.candidates
    assert candidate.settings == {"host": "imap.example.com", "port": 993}
    assert candidate.servers == (
        MailServer("imap", "imap.example.com", 993, "tls", None, None, True, ("IDLE",)),
    )
    assert candidate.hints == (Hint("Use an app password", "https://x.example"),)
    assert found.sources == (SourceReport("mx", "nothing", None),)
    assert found.hints == ()


async def test_a_sign_in_with_a_code(make_client: Callable) -> None:
    started = FakeApi(
        {
            "sign_in_id": "sgn_1",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://login.example/device",
            "expires_at": "2026-10-09T12:15:00Z",
            "interval": 5,
        }
    )
    begun = await make_client(started).start_device_oauth("microsoft", "acc_1")
    assert started.call() == (
        "POST",
        "/v1/oauth/microsoft/device",
        {},
        {"account_id": "acc_1"},
    )
    assert begun.user_code == "ABCD-EFGH" and begun.interval == 5
    assert begun.expires_at == datetime(2026, 10, 9, 12, 15, tzinfo=UTC)
    waiting = FakeApi({"connected": False, "account": None})
    state = await make_client(waiting).poll_device_oauth("microsoft", "sgn_1")
    assert waiting.call()[:2] == ("POST", "/v1/oauth/microsoft/device/sgn_1")
    assert state.connected is False and state.account is None
    done = FakeApi({"connected": True, "account": ACCOUNT})
    connected = await make_client(done).poll_device_oauth("microsoft", "sgn_1")
    assert connected.account is not None and connected.account.id == "acc_1"
