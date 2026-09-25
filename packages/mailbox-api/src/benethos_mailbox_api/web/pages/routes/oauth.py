"""Connecting an account by OAuth: off to the provider, and back.

The session cookie is ``SameSite=Strict``, so the browser leaves it out
when the provider sends it back. ``callback`` therefore needs no session:
it only bounces the browser on to ``finish``, a navigation from this site
that carries the cookie again. ``finish`` needs the session; the sign-in's
``state`` belongs to the user who started it, so a code slipped to someone
else is refused.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ....data.models import ProviderType
from ...services import OAuth
from ...urls import oauth_callback
from ..deps import Actor, Viewer
from ..forms import failing
from ..templates import back, local_path, render

router = APIRouter()


def _provider(value: str) -> ProviderType | None:
    try:
        return ProviderType(value)
    except ValueError:
        return None


@router.post("/oauth/{provider}/start")
async def start(
    request: Request, caller: Actor, provider: str, oauth: OAuth
) -> Response:
    form = await request.form()
    account_id = str(form.get("account_id") or "") or None
    fallback = f"/ui/accounts/{account_id}" if account_id else "/ui/accounts/new"
    here = local_path(str(form.get("back") or ""), fallback)
    kind = _provider(provider)
    if kind is None:
        return back(here, error=f"Unknown provider: {provider}")
    with failing(here):
        url = oauth.start(
            caller,
            kind,
            oauth_callback(request, kind),
            account_id=account_id,
            login_hint=str(form.get("login_hint") or "").strip() or None,
        )
    return RedirectResponse(url, status_code=303)


@router.get("/oauth/{provider}/callback")
async def callback(request: Request, provider: str) -> HTMLResponse:
    """Back from the provider: on to ``finish``, from this site."""
    kept = [
        (k, v)
        for k, v in request.query_params.multi_items()
        if k in ("code", "state", "error", "error_description")
    ]
    target = f"/ui/oauth/{provider}/finish?{urlencode(kept)}"
    return render(request, "pages/oauth_bounce.html", page="oauth", target=target)


@router.get("/oauth/{provider}/finish")
async def finish(
    request: Request, caller: Viewer, provider: str, oauth: OAuth
) -> Response:
    query = request.query_params
    kind = _provider(provider)
    state = query.get("state", "")
    if kind is None:
        return back("/ui/accounts", error=f"Unknown provider: {provider}")
    if query.get("error"):
        oauth.cancel(state)
        reason = query.get("error_description") or query["error"]
        return back("/ui/accounts", error=f"{kind.value} did not sign in: {reason}")
    with failing("/ui/accounts"):
        account = await oauth.finish(caller, kind, state, query.get("code", ""))
    return back(f"/ui/accounts/{account.id}", f"{account.email} signed in.")
