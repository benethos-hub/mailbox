"""A user's tokens: a new one, shown once, and revoking one or several.
They are listed on the Access tab of the user's page."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from benethos_mailbox_common.values import text

from ....common.clock import utc_now
from ...services import Tokens, Users
from ..deps import Actor
from ..forms import FormError, failing
from ..session import show_once
from ..templates import back
from .users import access_tab, typed_token, user_page

router = APIRouter()

# Longer than that is a token without an end: leave the field empty for one.
MAX_TOKEN_DAYS = 3650


@router.post("/users/{user_id}/tokens")
async def create_token(
    request: Request, caller: Actor, user_id: str, users: Users, tokens: Tokens
) -> Response:
    form = await request.form()
    here = access_tab(user_id)
    typed = typed_token(form)
    name, days = typed["name"], typed["days"]
    with failing(
        here,
        again=lambda err: user_page(
            request, caller, user_id, users, token_form=form, err=err
        ),
    ):
        if days and not (days.isdigit() and 1 <= int(days) <= MAX_TOKEN_DAYS):
            raise FormError(
                f"Days valid must be a whole number from 1 to {MAX_TOKEN_DAYS}."
            )
        expires_at = utc_now() + timedelta(days=int(days)) if days else None
        _, plain = tokens.create_token(caller, user_id, name, expires_at)
    # Shown on the next page, once, and never in the URL.
    show_once(request, f"token:{user_id}", plain)
    return back(request, here)


@router.post("/users/{user_id}/tokens/{token_id}/revoke")
async def revoke_token(
    request: Request, caller: Actor, user_id: str, token_id: str, tokens: Tokens
) -> Response:
    here = access_tab(user_id)
    with failing(here):
        token = tokens.revoke_token(caller, user_id, token_id)
    return back(request, here, f"Token {token.name} revoked.")


@router.post("/users/{user_id}/tokens/revoke")
async def revoke_tokens(
    request: Request,
    caller: Actor,
    user_id: str,
    tokens: Tokens,
    token: Annotated[list[str] | None, Form()] = None,
) -> Response:
    """The tokens ticked in the list, at once."""
    here = access_tab(user_id)
    with failing(here):
        revoked = tokens.revoke_tokens(caller, user_id, token or [])
    return back(request, here, f"{text.plural(len(revoked), 'token')} revoked.")
