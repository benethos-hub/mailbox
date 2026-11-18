"""Passkeys on the page Second factor: one made by the browser, renamed
and removed, and one of another user's removed from its page
(docs/AUTHENTICATION.md 5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from ....common.clock import utc_now
from ....domain.auth import SETUP, Answer
from ...services import PasskeyDevices
from ...urls import passkey_party, passkeys_work
from ..deps import Actor
from ..forms import failing
from ..passkeys import answered
from ..session import PendingPasskey, session_of, show_once
from ..templates import back
from .factor import CODES, FACTOR_PAGE
from .users import access_tab

router = APIRouter()

SIGNED_OUT = "Other sessions are signed out."
ELSEWHERE = (
    "Passkeys work at a name over HTTPS, or at localhost. Open the UI at its "
    "public address."
)


@router.post("/second-factor/passkeys/begin")
async def begin(
    request: Request,
    caller: Actor,
    passkeys: PasskeyDevices,
    name: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    party = passkey_party(request)
    if not passkeys_work(party):
        return back(request, FACTOR_PAGE, error=ELSEWHERE)
    proof = answered(request, passkey)
    with failing(FACTOR_PAGE):
        begun = await passkeys.begin(caller, name, password, party, code, proof)
    session_of(request).passkey = PendingPasskey(
        begun.name, begun.begun.options, begun.begun.challenge, utc_now() + SETUP
    )
    return back(request, FACTOR_PAGE)


@router.post("/second-factor/passkeys/confirm")
async def confirm(
    request: Request,
    caller: Actor,
    passkeys: PasskeyDevices,
    answer: Annotated[str, Form()] = "",
) -> Response:
    session = session_of(request)
    setup, session.passkey = session.passkey, None
    if setup is None or setup.until <= utc_now():
        return back(request, FACTOR_PAGE, error="The setup ran out. Start again.")
    if not answer:
        return back(request, FACTOR_PAGE, error="No passkey was made. Start again.")
    made = Answer(passkey_party(request), setup.challenge, answer)
    with failing(FACTOR_PAGE):
        added = passkeys.confirm(caller, setup.name, made)
    # This session carries on with the new passkey, every other one of the
    # user ends at its next request.
    session.factor = added.stamp
    if added.recovery_codes:
        show_once(request, CODES, "\n".join(added.recovery_codes))
        return back(request, FACTOR_PAGE, f"Second factor on. {SIGNED_OUT}")
    return back(request, FACTOR_PAGE, f"Passkey {setup.name} added. {SIGNED_OUT}")


@router.post("/second-factor/passkeys/cancel")
async def cancel(request: Request, _: Actor) -> Response:
    session_of(request).passkey = None
    return back(request, FACTOR_PAGE)


@router.post("/second-factor/passkeys/rename")
async def rename(
    request: Request,
    caller: Actor,
    passkeys: PasskeyDevices,
    device: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
) -> Response:
    with failing(FACTOR_PAGE):
        passkeys.rename(caller, device, name)
    return back(request, FACTOR_PAGE, "Passkey renamed.")


@router.post("/second-factor/passkeys/remove")
async def remove_own(
    request: Request,
    caller: Actor,
    passkeys: PasskeyDevices,
    device: Annotated[list[str] | None, Form()] = None,
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    """One passkey, or those ticked in the list, after one password and one
    code or passkey."""
    proof = answered(request, passkey)
    with failing(FACTOR_PAGE):
        stamp = await passkeys.remove_own(caller, device or [], password, code, proof)
    session_of(request).factor = stamp
    if stamp is None:
        return back(request, FACTOR_PAGE, "Passkey removed. The second factor is off.")
    return back(request, FACTOR_PAGE, f"Passkey removed. {SIGNED_OUT}")


@router.post("/users/{user_id}/second-factor/passkeys/{passkey_id}/remove")
async def remove_passkey(
    request: Request,
    user_id: str,
    passkey_id: str,
    caller: Actor,
    passkeys: PasskeyDevices,
) -> Response:
    page = access_tab(user_id)
    with failing(page):
        passkeys.remove_passkey(caller, user_id, passkey_id)
    return back(request, page, "Passkey removed. The user's sessions end.")
