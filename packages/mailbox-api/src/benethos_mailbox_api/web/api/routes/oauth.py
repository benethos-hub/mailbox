"""Connecting an account by OAuth. The API starts the sign-in; the browser
comes back to the configuration UI, which finishes it."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ....data.models import ProviderType
from ...services import OAuth
from ...urls import oauth_callback
from ..deps import Caller
from ..schemas import OAuthStart, OAuthStarted

router = APIRouter(prefix="/oauth", tags=["accounts"])


@router.post("/{provider}/start")
async def start_oauth(
    provider: ProviderType,
    data: OAuthStart,
    request: Request,
    caller: Caller,
    oauth: OAuth,
) -> OAuthStarted:
    """Where to send a browser to sign in at the provider: to connect a new
    account (needs `create_account`) or, with `account_id`, to sign that
    account in again (needs `update_account`). The provider sends the
    browser back to `/ui/oauth/{provider}/callback`, where the person signs
    in to the UI as the same user and the account is connected. Valid for
    ten minutes. `501` without an OAuth app for the provider."""
    url = oauth.start(
        caller,
        provider,
        oauth_callback(request, provider),
        account_id=data.account_id,
        login_hint=data.login_hint,
    )
    return OAuthStarted(url=url)
