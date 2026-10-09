"""The second factor: the person's own page with its devices, to add,
rename and remove one and to make new recovery codes, and the removal of
another user's devices from its page (docs/AUTHENTICATION.md 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ....common.clock import utc_now
from ....data.secrets import totp
from ....domain.auth import MAX_DEVICE_NAME, MAX_DEVICES, SETUP
from ...services import Factors
from ...urls import public_host
from ..deps import Actor, Viewer
from ..forms import failing
from ..qr import data_uri
from ..session import PendingSetup, session_of, show_once, take_once
from ..templates import back, render

router = APIRouter()

FACTOR_PAGE = "/ui/second-factor"
# The issuer an authenticator app shows above the code.
ISSUER = "Mailbox"
# Where the recovery codes wait for the next page, one per line.
CODES = "recovery_codes"
SIGNED_OUT = "Other sessions are signed out."


@router.get("/second-factor")
async def factor_page(
    request: Request, caller: Viewer, factors: Factors
) -> HTMLResponse:
    session = session_of(request)
    setup = session.setup
    if setup is not None and setup.until <= utc_now():
        session.setup = setup = None
    shown = take_once(request, CODES)
    return render(
        request,
        "pages/second_factor.html",
        page="factor",
        factor=factors.mine(caller),
        codes=shown.split("\n") if shown else None,
        setup=setup,
        qr=data_uri(_uri(request, caller.name, setup)) if setup else None,
        secret=_grouped(totp.base32(setup.secret)) if setup else None,
        minutes=int(SETUP.total_seconds() // 60),
        max_devices=MAX_DEVICES,
        max_name=MAX_DEVICE_NAME,
    )


@router.post("/second-factor/begin")
async def begin(
    request: Request,
    caller: Actor,
    factors: Factors,
    name: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        kept, secret = await factors.begin(caller, name, password, code)
    session_of(request).setup = PendingSetup(kept, secret, utc_now() + SETUP)
    return back(request, FACTOR_PAGE)


@router.post("/second-factor/confirm")
async def confirm(
    request: Request,
    caller: Actor,
    factors: Factors,
    code: Annotated[str, Form()] = "",
) -> Response:
    session = session_of(request)
    setup = session.setup
    if setup is None or setup.until <= utc_now():
        session.setup = None
        return back(request, FACTOR_PAGE, error="The setup ran out. Start again.")
    with failing(FACTOR_PAGE):
        codes, stamp = factors.confirm(caller, setup.name, setup.secret, code)
    # This session carries on with the new device, every other one of the
    # user ends at its next request.
    session.factor = stamp
    session.setup = None
    if codes:
        show_once(request, CODES, "\n".join(codes))
        return back(request, FACTOR_PAGE, f"Second factor on. {SIGNED_OUT}")
    return back(request, FACTOR_PAGE, f"Device {setup.name} added. {SIGNED_OUT}")


@router.post("/second-factor/cancel")
async def cancel(request: Request, _: Actor) -> Response:
    session_of(request).setup = None
    return back(request, FACTOR_PAGE)


@router.post("/second-factor/codes")
async def renew_codes(
    request: Request,
    caller: Actor,
    factors: Factors,
    password: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        codes = await factors.renew_codes(caller, password)
    show_once(request, CODES, "\n".join(codes))
    return back(request, FACTOR_PAGE, "New recovery codes. The old ones work no more.")


@router.post("/second-factor/rename")
async def rename(
    request: Request,
    caller: Actor,
    factors: Factors,
    device: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        factors.rename(caller, device, name)
    return back(request, FACTOR_PAGE, "Device renamed.")


@router.post("/second-factor/remove")
async def remove_own(
    request: Request,
    caller: Actor,
    factors: Factors,
    device: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        stamp = await factors.remove_own(caller, device, password, code)
    session_of(request).factor = stamp
    if stamp is None:
        return back(request, FACTOR_PAGE, "Device removed. The second factor is off.")
    return back(request, FACTOR_PAGE, f"Device removed. {SIGNED_OUT}")


@router.post("/users/{user_id}/second-factor/remove")
async def remove(
    request: Request, user_id: str, caller: Actor, factors: Factors
) -> Response:
    page = f"/ui/users/{user_id}"
    with failing(page):
        factors.remove(caller, user_id)
    return back(request, page, "Second factor removed. The user's sessions end.")


@router.post("/users/{user_id}/second-factor/devices/{device_id}/remove")
async def remove_device(
    request: Request, user_id: str, device_id: str, caller: Actor, factors: Factors
) -> Response:
    page = f"/ui/users/{user_id}"
    with failing(page):
        factors.remove_device(caller, user_id, device_id)
    return back(request, page, "Device removed. The user's sessions end.")


def _uri(request: Request, name: str, setup: PendingSetup) -> str:
    """What the QR code carries: the user name with the host of the
    service, so two deployments show apart in the app."""
    return totp.uri(setup.secret, ISSUER, f"{name}@{public_host(request)}")


def _grouped(text: str) -> str:
    """The secret in groups of four, easier to type."""
    return " ".join(text[i : i + 4] for i in range(0, len(text), 4))
