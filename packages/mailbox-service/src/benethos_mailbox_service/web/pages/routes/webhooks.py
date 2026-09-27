"""Webhooks: list, create, one with its delivery log, remove (docs/UI.md,
6.4). A webhook has no change: the API has none. A person removes it and
creates it anew."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from ....data.models import WebhookCreate
from ....data.models.webhooks import EVENT_TYPES
from ....domain.access import Access
from ...services import Webhooks, get_accounts
from ..deps import Actor, Viewer, emails_of
from ..forms import FormError, failing, first_problem
from ..session import show_once, take_once
from ..templates import back, render

router = APIRouter()


def _readable(request: Request, caller: Access) -> list[Any]:
    """The accounts a webhook of the caller can hear of."""
    return get_accounts(request).list(caller, may="list_changes")


@router.get("/webhooks")
async def list_webhooks(
    request: Request, caller: Viewer, webhooks: Webhooks
) -> HTMLResponse:
    return render(
        request,
        "pages/webhooks.html",
        page="webhooks",
        webhooks=webhooks.list_webhooks(caller),
        names=emails_of(get_accounts(request).list(caller)),
        can_create=caller.allows("create_webhook"),
    )


@router.get("/webhooks/new")
async def new_webhook(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_webhook")
    return render(
        request,
        "pages/webhook_new.html",
        page="webhooks",
        events=EVENT_TYPES,
        accounts=_readable(request, caller),
    )


def _request_of(form: Any) -> WebhookCreate:
    every = form.get("every") == "1"
    accounts = [str(a) for a in form.getlist("accounts")]
    if not every and not accounts:
        raise FormError("Choose the accounts, or every account.")
    try:
        return WebhookCreate(
            url=str(form.get("url") or "").strip(),
            events=[str(e) for e in form.getlist("events")],
            accounts=None if every else accounts,
        )
    except ValidationError as exc:
        raise FormError(first_problem(exc)) from None


@router.post("/webhooks")
async def create_webhook(
    request: Request, caller: Actor, webhooks: Webhooks
) -> Response:
    form = await request.form()
    with failing("/ui/webhooks/new"):
        created = webhooks.create_webhook(caller, _request_of(form))
    # Shown on the next page, once, and never in the URL.
    show_once(request, f"secret:{created.id}", created.secret)
    return back(request, f"/ui/webhooks/{created.id}", "Webhook created.")


@router.get("/webhooks/{webhook_id}")
async def webhook(
    request: Request, caller: Viewer, webhook_id: str, webhooks: Webhooks
) -> HTMLResponse:
    found = webhooks.get_webhook(caller, webhook_id)
    return render(
        request,
        "pages/webhook.html",
        page="webhooks",
        webhook=found,
        attempts=webhooks.attempts(caller, webhook_id),
        names=emails_of(get_accounts(request).list(caller)),
        secret=take_once(request, f"secret:{webhook_id}"),
        can_delete=caller.allows("delete_webhook"),
    )


@router.post("/webhooks/{webhook_id}/delete")
async def delete_webhook(
    request: Request, caller: Actor, webhook_id: str, webhooks: Webhooks
) -> Response:
    with failing(f"/ui/webhooks/{webhook_id}"):
        webhooks.delete_webhook(caller, webhook_id)
    return back(request, "/ui/webhooks", "Webhook removed.")
