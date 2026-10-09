"""Discovery from an address alone, and the sign-in with a code at a
provider that connects an account or signs it in again."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, path
from ..models import (
    Candidate,
    DeviceSignIn,
    DeviceSignInState,
    Discovery,
    Hint,
    MailServer,
    SourceReport,
)
from .accounts import account
from .readings import time


def discover_account(email: str) -> Call[Discovery]:
    """The ways to connect ``email``: the kind of account, its servers,
    how it signs in, the recommended one first."""
    return Call("POST", path("discovery"), _discovery, json={"email": email})


def start_device_oauth(
    provider: str, account_id: str | None = None
) -> Call[DeviceSignIn]:
    """Begin a sign-in with a code at ``provider``, e.g. ``microsoft``: to
    connect a new account, or with ``account_id`` to sign that one in
    again."""
    return Call(
        "POST",
        path("oauth", provider, "device"),
        _started,
        json=given({"account_id": account_id}),
    )


def poll_device_oauth(provider: str, sign_in_id: str) -> Call[DeviceSignInState]:
    """Whether the person signed in yet. Asked no sooner than the sign-in's
    ``interval``."""
    return Call(
        "POST",
        path("oauth", provider, "device", sign_in_id),
        lambda found: DeviceSignInState(
            connected=bool(found["connected"]),
            account=account(found["account"]) if found.get("account") else None,
        ),
    )


def _discovery(found: dict[str, Any]) -> Discovery:
    return Discovery(
        email=str(found["email"]),
        domain=str(found["domain"]),
        candidates=tuple(_candidate(c) for c in found.get("candidates", [])),
        hints=_hints(found),
        sources=tuple(
            SourceReport(str(s["source"]), str(s["outcome"]), s.get("message"))
            for s in found.get("sources", [])
        ),
    )


def _candidate(item: dict[str, Any]) -> Candidate:
    return Candidate(
        provider=str(item["provider"]),
        name=item.get("name"),
        credential=str(item["credential"]),
        oauth_provider=item.get("oauth_provider"),
        servers=tuple(_server(s) for s in item.get("servers", [])),
        hints=_hints(item),
        source=str(item["source"]),
        confirmed=bool(item.get("confirmed", False)),
        settings=dict(item.get("settings", {})),
    )


def _server(item: dict[str, Any]) -> MailServer:
    return MailServer(
        protocol=str(item["protocol"]),
        host=str(item["host"]),
        port=int(item["port"]),
        security=str(item["security"]),
        username=item.get("username"),
        path=item.get("path"),
        reachable=item.get("reachable"),
        capabilities=tuple(item.get("capabilities", [])),
    )


def _hints(item: dict[str, Any]) -> tuple[Hint, ...]:
    return tuple(Hint(str(h["text"]), h.get("url")) for h in item.get("hints", []))


def _started(found: dict[str, Any]) -> DeviceSignIn:
    return DeviceSignIn(
        sign_in_id=str(found["sign_in_id"]),
        user_code=str(found["user_code"]),
        verification_uri=str(found["verification_uri"]),
        expires_at=time(found["expires_at"]),
        interval=int(found["interval"]),
    )
