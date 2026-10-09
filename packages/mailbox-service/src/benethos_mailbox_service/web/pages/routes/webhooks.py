"""Webhooks: list, create, one with its delivery log, change, a new
secret, remove (docs/UI.md, 6.4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....data.models import CHANGE_KINDS, Webhook, WebhookCreate, WebhookUpdate
from ....domain.rights import Access
from ....domain.webhooks import WebhookService
from ...services import Webhooks, get_accounts
from ..deps import Actor, Viewer, account_names
from ..filters import Field, filter_bar
from ..forms import REFUSED, FormError, failing, model_of, text_of
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
    names = account_names(request, caller)
    bar = filter_bar(
        request,
        (
            Field("account", "Account", "select", list(names.items())),
            Field("failing", "failing", "flag"),
        ),
        search=Field("url", "URL"),
    )
    return render(
        request,
        "pages/webhooks.html",
        page="webhooks",
        bar=bar,
        webhooks=webhooks.list_webhooks(
            caller,
            url=bar.value("url") or None,
            account=bar.value("account") or None,
            failing=True if bar.value("failing") else None,
        ),
        names=names,
        can_create=caller.allows("create_webhook"),
    )


@router.get("/webhooks/new")
async def new_webhook(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_webhook")
    return _new_webhook_page(request, caller)


def _new_webhook_page(
    request: Request, caller: Access, form: Any = None, err: str | None = None
) -> HTMLResponse:
    """The editor of a new webhook, empty or as ``form`` held it."""
    return render(
        request,
        "pages/webhook_new.html",
        page="webhooks",
        status_code=REFUSED if err else 200,
        err=err,
        typed=_typed(form) if form is not None else None,
        events=CHANGE_KINDS,
        accounts=_readable(request, caller),
    )


def _typed(form: Any) -> dict[str, Any]:
    """The fields of a new webhook as they were submitted."""
    return {
        "url": text_of(form, "url"),
        "events": [str(e) for e in form.getlist("events")],
        "every": form.get("every") == "1",
        "accounts": [str(a) for a in form.getlist("accounts")],
    }


def _shown(webhook: Webhook) -> dict[str, Any]:
    """The fields of a webhook as its Change card shows them."""
    return {
        "url": webhook.url,
        "events": list(webhook.events),
        "every": webhook.accounts is None,
        "accounts": list(webhook.accounts or []),
    }


def _fields_of(form: Any) -> dict[str, Any]:
    """The URL, events and accounts of a webhook form, for the API's
    shapes. Every account is ``accounts`` None."""
    typed = _typed(form)
    if not typed["every"] and not typed["accounts"]:
        raise FormError("Choose the accounts, or every account.")
    return {
        "url": typed["url"],
        "events": typed["events"],
        "accounts": None if typed["every"] else typed["accounts"],
    }


def _request_of(form: Any) -> WebhookCreate:
    return model_of(WebhookCreate, _fields_of(form))


@router.post("/webhooks")
async def create_webhook(
    request: Request, caller: Actor, webhooks: Webhooks
) -> Response:
    form = await request.form()
    with failing(
        "/ui/webhooks/new",
        again=lambda err: _new_webhook_page(request, caller, form, err),
    ):
        created = webhooks.create_webhook(caller, _request_of(form))
    # Shown on the next page, once, and never in the URL.
    show_once(request, f"secret:{created.id}", created.secret)
    return back(request, f"/ui/webhooks/{created.id}", "Webhook created.")


@router.get("/webhooks/{webhook_id}")
async def webhook(
    request: Request, caller: Viewer, webhook_id: str, webhooks: Webhooks
) -> HTMLResponse:
    return _webhook_page(request, caller, webhook_id, webhooks)


def _webhook_page(
    request: Request,
    caller: Access,
    webhook_id: str,
    webhooks: WebhookService,
    form: Any = None,
    err: str | None = None,
) -> HTMLResponse:
    """A webhook's page, its Change card as ``form`` held it if given."""
    found = webhooks.get_webhook(caller, webhook_id)
    return render(
        request,
        "pages/webhook.html",
        page="webhooks",
        status_code=REFUSED if err else 200,
        err=err,
        webhook=found,
        names=account_names(request, caller),
        secret=take_once(request, f"secret:{webhook_id}"),
        typed=_typed(form) if form is not None else _shown(found),
        events=CHANGE_KINDS,
        accounts=_readable(request, caller),
        can_update=caller.allows("update_webhook"),
        can_renew=caller.allows("renew_webhook_secret"),
        can_delete=caller.allows("delete_webhook"),
    )


@router.post("/webhooks/{webhook_id}")
async def update_webhook(
    request: Request, caller: Actor, webhook_id: str, webhooks: Webhooks
) -> Response:
    form = await request.form()
    here = f"/ui/webhooks/{webhook_id}"
    with failing(
        here,
        again=lambda err: _webhook_page(
            request, caller, webhook_id, webhooks, form, err
        ),
    ):
        changes = model_of(WebhookUpdate, _fields_of(form))
        webhooks.update_webhook(caller, webhook_id, changes)
    return back(request, here, "Saved.")


@router.post("/webhooks/{webhook_id}/secret")
async def renew_webhook_secret(
    request: Request, caller: Actor, webhook_id: str, webhooks: Webhooks
) -> Response:
    here = f"/ui/webhooks/{webhook_id}"
    with failing(here):
        renewed = webhooks.renew_webhook_secret(caller, webhook_id)
    # Shown on the next page, once, and never in the URL.
    show_once(request, f"secret:{webhook_id}", renewed.secret)
    return back(request, here, "New secret made. The one before stops at once.")


@router.post("/webhooks/{webhook_id}/delete")
async def delete_webhook(
    request: Request, caller: Actor, webhook_id: str, webhooks: Webhooks
) -> Response:
    with failing(f"/ui/webhooks/{webhook_id}"):
        webhooks.delete_webhook(caller, webhook_id)
    return back(request, "/ui/webhooks", "Webhook removed.")
