"""The caller and its accounts: ``/v1/me``, which every token may ask,
read into ``Me``, and the catalogue of rights, read into
``Permissions``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, path
from ..models import Me, MeAccount, Permissions, Sending


def get_me() -> Call[Me]:
    return Call("GET", path("me"), _me)


def list_permissions() -> Call[Permissions]:
    """Every group of rights and the operations it allows, and which
    groups belong to the service."""
    return Call(
        "GET",
        path("permissions"),
        lambda found: Permissions(
            groups={g: tuple(ops) for g, ops in found["groups"].items()},
            service=tuple(found["service"]),
        ),
    )


def _me(found: dict[str, Any]) -> Me:
    return Me(
        user_id=str(found["user_id"]),
        name=str(found["name"]),
        accounts=[
            MeAccount(
                id=str(a["id"]),
                email=str(a["email"]),
                display_name=a.get("display_name"),
                operations=frozenset(a.get("operations", [])),
                warnings=frozenset(a.get("warnings", [])),
                sending=tuple(_sending(s) for s in a.get("sending", [])),
                capabilities=(
                    frozenset(a["capabilities"]) if "capabilities" in a else None
                ),
            )
            for a in found.get("accounts", [])
        ],
        operations=frozenset(found.get("operations", [])),
    )


def _sending(item: dict[str, Any]) -> Sending:
    recipients = item.get("recipients")
    return Sending(
        recipients=tuple(recipients) if recipients is not None else None,
        max_per_day=item.get("max_sends_per_day"),
        left=item.get("sends_left"),
    )
