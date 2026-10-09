"""A user's second factor: its devices read, one removed or every one,
read into ``SecondFactor``. Only its owner adds a device, in the UI."""

from __future__ import annotations

from typing import Any

from ..calls import Call, nothing, path
from ..models import SecondFactor, TotpDevice
from .readings import maybe_time, time


def get_second_factor(user_id: str) -> Call[SecondFactor]:
    return Call("GET", path("users", user_id, "second-factor"), _factor)


def remove_second_factor(user_id: str) -> Call[None]:
    """Every device of the user: its password alone signs in then, e.g.
    after every device is lost. Its sessions end."""
    return Call("DELETE", path("users", user_id, "second-factor"), nothing)


def remove_totp_device(user_id: str, device_id: str) -> Call[None]:
    """One authenticator app of the user. Its sessions end."""
    return Call(
        "DELETE", path("users", user_id, "second-factor", "totp", device_id), nothing
    )


def _factor(found: dict[str, Any]) -> SecondFactor:
    return SecondFactor(
        totp=tuple(
            TotpDevice(
                id=str(d["id"]),
                name=str(d["name"]),
                created_at=time(d["created_at"]),
                last_used_at=maybe_time(d.get("last_used_at")),
            )
            for d in found["totp"]
        ),
        recovery_codes_left=int(found["recovery_codes_left"]),
    )
