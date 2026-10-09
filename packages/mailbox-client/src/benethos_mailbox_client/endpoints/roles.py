"""Roles: listed, made, read, replaced and deleted, read into
``Role``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..calls import Call, given, nothing, path
from ..models import Grant, Role
from .rights import grant, grants_body


def list_roles() -> Call[list[Role]]:
    return Call("GET", path("roles"), lambda found: [role(r) for r in found])


def create_role(
    role_id: str,
    *,
    service: list[str] | None = None,
    grants: Sequence[Grant] | None = None,
) -> Call[Role]:
    """A role named ``role_id``, with rights the caller holds itself."""
    return Call(
        "POST",
        path("roles"),
        role,
        json=given({"id": role_id, "service": service, "grants": grants_body(grants)}),
    )


def get_role(role_id: str) -> Call[Role]:
    return Call("GET", path("roles", role_id), role)


def replace_role(
    role_id: str,
    *,
    service: list[str] | None = None,
    grants: Sequence[Grant] | None = None,
) -> Call[Role]:
    """The role's rights anew: what is left out is none. It takes effect
    at once for every user with the role."""
    return Call(
        "PUT",
        path("roles", role_id),
        role,
        json={
            "service": list(service or []),
            "grants": grants_body(grants) or [],
        },
    )


def delete_role(role_id: str) -> Call[None]:
    """Only a role no user holds goes."""
    return Call("DELETE", path("roles", role_id), nothing)


def role(item: dict[str, Any]) -> Role:
    return Role(
        id=str(item["id"]),
        service=tuple(item.get("service", [])),
        grants=tuple(grant(g) for g in item.get("grants", [])),
    )
