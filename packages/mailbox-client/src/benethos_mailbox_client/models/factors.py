"""A user's second factor for the UI sign-in: its devices, never a
secret of theirs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TotpDevice:
    """An authenticator app of a user, by the name it was given."""

    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class SecondFactor:
    """The devices of each method, TOTP so far, and how many recovery
    codes are left. No device: the password alone signs in."""

    totp: tuple[TotpDevice, ...]
    recovery_codes_left: int
