"""Accounts: listed, connected, read, changed, verified and removed,
read into ``Account``. Credentials go in, they never come back."""

from __future__ import annotations

from types import EllipsisType
from typing import Any

from ..calls import Call, given, nothing, path
from ..models import Account, Paged, StoredCredential
from .readings import paged, time


def list_accounts(
    *,
    address: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[Account]]:
    """The accounts the caller may list, by address. ``address`` is a part
    of it regardless of case, ``provider`` and ``status`` narrow."""
    return Call(
        "GET",
        path("accounts"),
        paged(account),
        params=given(
            {
                "address": address,
                "provider": provider,
                "status": status,
                "limit": limit,
                "cursor": cursor,
            }
        ),
    )


def create_account(
    provider: str,
    email: str,
    *,
    display_name: str | None = None,
    settings: dict[str, Any] | None = None,
    credentials: dict[str, str] | None = None,
) -> Call[Account]:
    """Connect a mailbox. The service tries it before it stores anything.
    ``credentials`` are secrets such as ``password``, stored encrypted."""
    return Call(
        "POST",
        path("accounts"),
        account,
        json=given(
            {
                "provider": provider,
                "email": email,
                "display_name": display_name,
                "settings": settings,
                "credentials": credentials,
            }
        ),
    )


def get_account(account_id: str) -> Call[Account]:
    return Call("GET", path("accounts", account_id), account)


def update_account(
    account_id: str,
    *,
    display_name: str | None | EllipsisType = ...,
    settings: dict[str, Any] | None = None,
    credentials: dict[str, str] | None = None,
) -> Call[Account]:
    """Change an account. Left out stays: ``display_name`` as ``...``,
    None removes it. ``settings`` are merged into the current ones, a
    value None removes one. New ``credentials`` are tried first."""
    body = given({"settings": settings, "credentials": credentials})
    if display_name is not ...:
        body["display_name"] = display_name
    return Call("PATCH", path("accounts", account_id), account, json=body)


def delete_account(account_id: str) -> Call[None]:
    """Remove the account and its credentials from the service. The
    mailbox at the provider stays as it is."""
    return Call("DELETE", path("accounts", account_id), nothing)


def verify_account(account_id: str) -> Call[Account]:
    """Log in to the account now: its status afterwards."""
    return Call("POST", path("accounts", account_id, "verify"), account)


def account(item: dict[str, Any]) -> Account:
    return Account(
        id=str(item["id"]),
        provider=str(item["provider"]),
        email=str(item["email"]),
        display_name=item.get("display_name"),
        status=str(item.get("status", "connected")),
        credentials=tuple(
            StoredCredential(str(c["field"]), time(c["updated_at"]))
            for c in item.get("credentials", [])
        ),
        settings=dict(item.get("settings", {})),
        capabilities=frozenset(item.get("capabilities", [])),
    )
