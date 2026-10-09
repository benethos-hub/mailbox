"""The caller and its accounts: ``/v1/me``, which every token may ask,
read into ``Me``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, path
from ..models import Me, MeAccount, Sending


def get_me() -> Call[Me]:
    return Call("GET", path("me"), _me)


def _me(found: dict[str, Any]) -> Me:
    return Me(
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
