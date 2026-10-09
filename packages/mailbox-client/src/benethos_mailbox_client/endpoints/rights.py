"""Grants as the API writes them, read and written for users and
roles alike."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..calls import given
from ..models import Grant
from .readings import maybe_time


def grant(item: dict[str, Any]) -> Grant:
    recipients, folders = item.get("recipients"), item.get("folders")
    return Grant(
        accounts=tuple(item["accounts"]),
        allow=tuple(item["allow"]),
        recipients=tuple(recipients) if recipients is not None else None,
        max_sends_per_day=item.get("max_sends_per_day"),
        folders=tuple(folders) if folders is not None else None,
        expires_at=maybe_time(item.get("expires_at")),
    )


def grants_body(grants: Sequence[Grant] | None) -> list[dict[str, Any]] | None:
    """The grants as a request carries them, what is None left out."""
    if grants is None:
        return None
    return [
        given(
            {
                "accounts": list(g.accounts),
                "allow": list(g.allow),
                "recipients": list(g.recipients) if g.recipients is not None else None,
                "max_sends_per_day": g.max_sends_per_day,
                "folders": list(g.folders) if g.folders is not None else None,
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
            }
        )
        for g in grants
    ]
