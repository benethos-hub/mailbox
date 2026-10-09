"""Users: listed, made, read, changed and deleted, and a password set
for one, read into ``User`` and ``NewPassword``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..calls import Call, given, nothing, path
from ..models import Grant, NewPassword, Paged, Secret, User
from .readings import maybe_time, paged
from .rights import grant, grants_body


def list_users(
    *,
    name: str | None = None,
    role: str | None = None,
    disabled: bool | None = None,
    ui_sign_in: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[User]]:
    """The users the caller may read, by name. ``name`` is a part of it
    regardless of case. ``ui_sign_in`` False: the API users."""
    return Call(
        "GET",
        path("users"),
        paged(user),
        params=given(
            {
                "name": name,
                "role": role,
                "disabled": disabled,
                "ui_sign_in": ui_sign_in,
                "limit": limit,
                "cursor": cursor,
            }
        ),
    )


def create_user(
    name: str,
    *,
    roles: list[str] | None = None,
    service: list[str] | None = None,
    grants: Sequence[Grant] | None = None,
    ui_sign_in: bool | None = None,
) -> Call[User]:
    """A new user with rights the caller holds itself. Without
    ``ui_sign_in`` it works with tokens only."""
    return Call(
        "POST",
        path("users"),
        user,
        json=given(
            {
                "name": name,
                "roles": roles,
                "service": service,
                "grants": grants_body(grants),
                "ui_sign_in": ui_sign_in,
            }
        ),
    )


def get_user(user_id: str) -> Call[User]:
    return Call("GET", path("users", user_id), user)


def update_user(
    user_id: str,
    *,
    name: str | None = None,
    roles: list[str] | None = None,
    service: list[str] | None = None,
    grants: Sequence[Grant] | None = None,
    disabled: bool | None = None,
    ui_sign_in: bool | None = None,
) -> Call[User]:
    """Change a user. What is left out stays, a list given replaces the
    one before."""
    return Call(
        "PATCH",
        path("users", user_id),
        user,
        json=given(
            {
                "name": name,
                "roles": roles,
                "service": service,
                "grants": grants_body(grants),
                "disabled": disabled,
                "ui_sign_in": ui_sign_in,
            }
        ),
    )


def delete_user(user_id: str) -> Call[None]:
    """The user and its tokens. What it sent stays in the send audit."""
    return Call("DELETE", path("users", user_id), nothing)


def set_password(user_id: str, password: str | None = None) -> Call[NewPassword]:
    """A password for a user with the UI sign-in, to change at its next
    sign-in. Without ``password`` the service makes a one-time password
    and answers it, this once."""
    return Call(
        "POST",
        path("users", user_id, "password"),
        lambda found: NewPassword(
            password=Secret(str(found["password"])) if found.get("password") else None,
            must_change=bool(found.get("must_change", True)),
        ),
        json=given({"password": password}),
    )


def user(item: dict[str, Any]) -> User:
    return User(
        id=str(item["id"]),
        name=str(item["name"]),
        roles=tuple(item.get("roles", [])),
        service=tuple(item.get("service", [])),
        grants=tuple(grant(g) for g in item.get("grants", [])),
        disabled=bool(item.get("disabled", False)),
        ui_sign_in=bool(item.get("ui_sign_in", False)),
        has_password=bool(item["has_password"]),
        must_change=bool(item["must_change"]),
        last_sign_in_at=maybe_time(item.get("last_sign_in_at")),
        second_factor=bool(item["second_factor"]),
    )
