"""TOTP, an authenticator app, on the page Second factor: a device added
from its QR code, renamed and removed, and one of another user's
devices removed from its page (docs/AUTHENTICATION.md 5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from ....common.clock import utc_now
from ....domain.auth import SETUP
from ...services import TotpDevices
from ..deps import Actor
from ..forms import failing
from ..passkeys import answered, first_way
from ..session import PendingTotp, session_of
from ..templates import back
from .factor import FACTOR_PAGE, device_added, devices_removed
from .users import access_tab

router = APIRouter()


@router.post("/second-factor/totp/begin")
async def begin(
    request: Request,
    caller: Actor,
    totp: TotpDevices,
    name: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    proof = answered(request, passkey)
    with failing(FACTOR_PAGE, dialog="add-device", first=first_way(code, passkey)):
        begun = await totp.begin(caller, name, password, code, proof)
    session_of(request).totp = PendingTotp(begun.name, begun.secret, utc_now() + SETUP)
    return back(request, FACTOR_PAGE)


@router.post("/second-factor/totp/confirm")
async def confirm(
    request: Request,
    caller: Actor,
    totp: TotpDevices,
    code: Annotated[str, Form()] = "",
) -> Response:
    session = session_of(request)
    setup = session.totp
    if setup is None or setup.until <= utc_now():
        session.totp = None
        return back(request, FACTOR_PAGE, error="The setup ran out. Start again.")
    with failing(FACTOR_PAGE):
        confirmed = totp.confirm(caller, setup.name, setup.secret, code)
    session.totp = None
    return device_added(request, confirmed, f"Device {setup.name} added.")


@router.post("/second-factor/totp/cancel")
async def cancel(request: Request, _: Actor) -> Response:
    session_of(request).totp = None
    return back(request, FACTOR_PAGE)


@router.post("/second-factor/totp/rename")
async def rename(
    request: Request,
    caller: Actor,
    totp: TotpDevices,
    device: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        totp.rename(caller, device, name)
    return back(request, FACTOR_PAGE, "Device renamed.")


@router.post("/second-factor/totp/remove")
async def remove_own(
    request: Request,
    caller: Actor,
    totp: TotpDevices,
    device: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    proof = answered(request, passkey)
    with failing(
        FACTOR_PAGE, dialog=f"remove-{device}", first=first_way(code, passkey)
    ):
        stamp = await totp.remove_own(caller, device, password, code, proof)
    return devices_removed(request, stamp, "Device removed.")


@router.post("/users/{user_id}/second-factor/totp/{device_id}/remove")
async def remove_device(
    request: Request, user_id: str, device_id: str, caller: Actor, totp: TotpDevices
) -> Response:
    page = access_tab(user_id)
    with failing(page):
        totp.remove_device(caller, user_id, device_id)
    return back(request, page, "Device removed. The user's sessions end.")


@router.post("/second-factor/totp/remove-ticked")
async def remove_ticked(
    request: Request,
    caller: Actor,
    totp: TotpDevices,
    device: Annotated[list[str] | None, Form()] = None,
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    """The devices ticked in the list, after one password and one code or
    passkey."""
    proof = answered(request, passkey)
    with failing(FACTOR_PAGE, dialog="remove-ticked", first=first_way(code, passkey)):
        stamp = await totp.remove_own_devices(
            caller, device or [], password, code, proof
        )
    return devices_removed(request, stamp, "Devices removed.")
