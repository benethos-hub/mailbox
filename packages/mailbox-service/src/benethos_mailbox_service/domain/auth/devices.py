"""What the devices of every method of the second factor share: a name
the person chose, unique among the devices of the method whatever the
case, and a limit per user (docs/mailbox-service/AUTHENTICATION.md 5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from ...errors import BadRequestError, ConflictError

# Devices of one method of one user, and the length of a device's name.
MAX_DEVICES = 10
MAX_DEVICE_NAME = 60
# A new device of any method not yet confirmed is dropped after this: a
# secret shown, or a passkey's registration begun.
SETUP = timedelta(minutes=15)


def checked_name(
    name: str, held: Sequence[tuple[str, str]], device_id: str | None, noun: str
) -> str:
    """``name`` as a device of the user may be called: not empty, not too
    long, no line breaks, not the name of another of ``held``, its devices
    as id and name. A new device, without ``device_id``, needs a free place
    too. ``noun`` names the device in the errors."""
    name = " ".join(name.split())
    if not name:
        raise BadRequestError(f"a {noun} needs a name")
    if len(name) > MAX_DEVICE_NAME:
        raise BadRequestError(
            f"a {noun}'s name has at most {MAX_DEVICE_NAME} characters"
        )
    wanted = name.casefold()
    if any(n.casefold() == wanted and i != device_id for i, n in held):
        raise ConflictError(f"a {noun} named {name} exists")
    if device_id is None and len(held) >= MAX_DEVICES:
        raise ConflictError(f"at most {MAX_DEVICES} {noun}s: remove one first")
    return name
