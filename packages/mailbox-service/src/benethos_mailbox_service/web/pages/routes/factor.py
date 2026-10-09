"""The second factor as a whole: the person's own page with a card per
method and the recovery codes, new recovery codes, and every method of
another user removed from its page (docs/AUTHENTICATION.md 2, 6). What
TOTP does on the page is in ``totp``."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

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
from ..session import PendingTotp, session_of, show_once, take_once
from ..templates import back, render

router = APIRouter()

FACTOR_PAGE = "/ui/second-factor"
# The issuer an authenticator app shows above the code.
ISSUER = "Mailbox"
# Where the recovery codes wait for the next page, one per line.
CODES = "recovery_codes"


@router.get("/second-factor")
async def factor_page(
    request: Request, caller: Viewer, factors: Factors
) -> HTMLResponse:
    session = session_of(request)
    setup = session.totp
    if setup is not None and setup.until <= utc_now():
        session.totp = setup = None
    shown = take_once(request, CODES)
    codes = shown.split("\n") if shown else None
    return render(
        request,
        "pages/second_factor.html",
        page="factor",
        factor=factors.mine(caller),
        codes=codes,
        codes_file=_codes_file(request, caller.name, codes) if codes else None,
        setup=setup,
        qr=data_uri(_uri(request, caller.name, setup)) if setup else None,
        secret=_grouped(totp.base32(setup.secret)) if setup else None,
        minutes=int(SETUP.total_seconds() // 60),
        max_devices=MAX_DEVICES,
        max_name=MAX_DEVICE_NAME,
    )


@router.post("/second-factor/codes")
async def renew_codes(
    request: Request,
    caller: Actor,
    factors: Factors,
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        codes = await factors.renew_codes(caller, password, code)
    show_once(request, CODES, "\n".join(codes))
    return back(request, FACTOR_PAGE, "New recovery codes. The old ones work no more.")


@router.post("/users/{user_id}/second-factor/remove")
async def remove(
    request: Request, user_id: str, caller: Actor, factors: Factors
) -> Response:
    page = f"/ui/users/{user_id}"
    with failing(page):
        factors.remove(caller, user_id)
    return back(request, page, "Second factor removed. The user's sessions end.")


def _uri(request: Request, name: str, setup: PendingTotp) -> str:
    """What the QR code carries: the user name with the host of the
    service, so two deployments show apart in the app."""
    return totp.uri(setup.secret, ISSUER, f"{name}@{public_host(request)}")


def _codes_file(request: Request, name: str, codes: list[str]) -> str:
    """The recovery codes as a text file to download, in a data URI: the
    page holds them, the service keeps none after showing them."""
    host = public_host(request)
    lines = [
        f"Recovery codes of {name} for {ISSUER} at {host}",
        f"Made {utc_now():%Y-%m-%d %H:%M} UTC. Each signs in once in place of",
        "a code of a device. New ones make these void.",
        "",
        *codes,
        "",
    ]
    text = "\r\n".join(lines)
    return "data:text/plain;charset=utf-8," + quote(text, safe="")


def _grouped(text: str) -> str:
    """The secret in groups of four, easier to type."""
    return " ".join(text[i : i + 4] for i in range(0, len(text), 4))
