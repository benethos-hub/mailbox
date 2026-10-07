"""Connecting an account by OAuth. In a browser: the API starts the
sign-in, and the browser comes back to the configuration UI, which
finishes it. With a code: the API starts the sign-in and is polled until
the person entered the code at the provider and signed in."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ....data.models import ProviderType
from ...services import OAuth
from ...urls import oauth_callback
from ..deps import Caller
from ..schemas import (
    DeviceOAuthStart,
    DeviceOAuthStarted,
    DeviceOAuthState,
    OAuthStart,
    OAuthStarted,
)

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
    ten minutes. `400` with the project's app where this service is not
    at localhost: the provider sends a browser back to localhost only, so
    sign in with a code. `501` without an OAuth app for the provider, or
    when connecting a kind of account this deployment does not offer."""
    url = oauth.start(
        caller,
        provider,
        oauth_callback(request, provider),
        account_id=data.account_id,
        login_hint=data.login_hint,
    )
    return OAuthStarted(url=url)


@router.post("/{provider}/device")
async def start_device_oauth(
    provider: ProviderType,
    data: DeviceOAuthStart,
    caller: Caller,
    oauth: OAuth,
) -> DeviceOAuthStarted:
    """A code to sign in with at the provider, on any device: to connect a
    new account (needs `create_account`) or, with `account_id`, to sign
    that account in again (needs `update_account`). Needs no address the
    provider sends a browser back to. The person opens
    `verification_uri` and enters `user_code`. Then poll
    `POST /v1/oauth/{provider}/device/{sign_in_id}` every `interval`
    seconds. `501` without an OAuth app for the provider, where it has no
    sign-in with a code, or when connecting a kind of account this
    deployment does not offer."""
    started = await oauth.start_device(caller, provider, account_id=data.account_id)
    return DeviceOAuthStarted(
        sign_in_id=started.id,
        user_code=started.user_code,
        verification_uri=started.verification_uri,
        expires_at=started.expires_at,
        interval=started.interval,
    )


@router.post("/{provider}/device/{sign_in_id}")
async def poll_device_oauth(
    provider: ProviderType,
    sign_in_id: str,
    caller: Caller,
    oauth: OAuth,
) -> DeviceOAuthState:
    """Whether the person signed in with the code. Then the account is
    connected, or signed in again, and comes with the answer, also on a
    later poll. Until then `connected` is false. A poll sooner than
    `interval` does not ask the provider. Only the user who started the
    sign-in can poll it. `400` when it is unknown, expired or was declined:
    start again."""
    account = await oauth.poll_device(caller, provider, sign_in_id)
    return DeviceOAuthState(connected=account is not None, account=account)
