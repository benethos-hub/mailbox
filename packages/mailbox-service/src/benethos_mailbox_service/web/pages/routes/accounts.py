"""Accounts: list, connect through autodiscovery, change, verify, delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import SecretStr

from ....data.models import ProviderType
from ....domain.discovery import connectable, sign_ins
from ...services import Accounts, Discoverer, get_oauth
from ..deps import Actor, Viewer
from ..forms import failing
from ..templates import back, render

router = APIRouter()

# Connection settings a form may carry, and which of them are numbers.
SETTING_FIELDS = (
    "host",
    "port",
    "security",
    "username",
    "smtp_host",
    "smtp_port",
    "smtp_security",
    "smtp_username",
)
NUMBERS = {"port", "smtp_port"}
SECURITY = ("tls", "starttls")


def _settings(form: Any) -> dict[str, str | int | bool]:
    """The filled-in connection fields. Empty ones are left out."""
    found: dict[str, str | int | bool] = {}
    for key in SETTING_FIELDS:
        value = str(form.get(key) or "").strip()
        if not value:
            continue
        found[key] = int(value) if key in NUMBERS and value.isdigit() else value
    return found


def _changed(
    current: dict[str, str | int | bool],
    submitted: dict[str, str | int | bool],
    sent: set[str],
) -> dict[str, str | int | bool | None]:
    """What the form changes: new or different values, and ``None`` for a
    field that was sent empty. A field the form did not send changes
    nothing. Unchanged settings are not passed on, so a rename does not log
    in to the provider again."""
    changed: dict[str, str | int | bool | None] = {
        key: value for key, value in submitted.items() if current.get(key) != value
    }
    for key in SETTING_FIELDS:
        if key in current and key in sent and key not in submitted:
            changed[key] = None
    return changed


def _password(form: Any) -> dict[str, SecretStr]:
    value = str(form.get("password") or "")
    return {"password": SecretStr(value)} if value else {}


@router.get("/accounts")
async def list_accounts(
    request: Request, caller: Viewer, accounts: Accounts
) -> HTMLResponse:
    return render(
        request,
        "pages/accounts.html",
        page="accounts",
        accounts=accounts.list(caller),
        can_create=caller.allows("create_account"),
    )


@router.get("/accounts/new")
async def new_account(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_account")
    return render(
        request,
        "pages/account_new.html",
        page="accounts",
        email="",
        discovery=None,
        security=SECURITY,
        oauth_providers=_oauth_providers(request),
    )


def _oauth_providers(request: Request) -> list[str]:
    """The providers an account can sign in with here, e.g. microsoft."""
    return [p.value for p in get_oauth(request).providers()]


@router.post("/accounts/discover")
async def discover(request: Request, caller: Actor, discovery: Discoverer) -> Response:
    """The ways to connect an address. A POST, so the address stays out of
    access logs, answered with the page itself: a lookup changes nothing."""
    form = await request.form()
    email = str(form.get("email") or "").strip()
    with failing("/ui/accounts/new"):
        found = await discovery.discover(caller, email)
    return render(
        request,
        "pages/account_new.html",
        page="accounts",
        email=email,
        discovery=found,
        usable=connectable(found.candidates),
        sign_ins=sign_ins(found.candidates, _oauth_providers(request)),
        security=SECURITY,
        oauth_providers=_oauth_providers(request),
    )


@router.post("/accounts")
async def create_account(
    request: Request, caller: Actor, accounts: Accounts
) -> Response:
    form = await request.form()
    email = str(form.get("email") or "").strip()
    settings = _settings(form)
    try:
        provider = ProviderType(str(form.get("provider") or ProviderType.IMAP))
    except ValueError:
        return back("/ui/accounts/new", error="Unknown provider.")
    with failing("/ui/accounts/new", f"{email}: "):
        account = await accounts.create(
            caller,
            provider,
            email,
            str(form.get("display_name") or "").strip() or None,
            settings,
            _password(form),
        )
    return back(f"/ui/accounts/{account.id}", f"{account.email} connected.")


@router.get("/accounts/{account_id}")
async def account(
    request: Request, caller: Viewer, account_id: str, accounts: Accounts
) -> HTMLResponse:
    found = accounts.get(caller, account_id)
    return render(
        request,
        "pages/account.html",
        page="accounts",
        account=found,
        can_read=caller.allows("list_messages", account_id),
        can_audit=caller.allows("list_sends", account_id),
        can_update=caller.allows("update_account", account_id),
        can_verify=caller.allows("verify_account", account_id),
        can_delete=caller.allows("delete_account", account_id),
        signs_in_with_oauth=accounts.signs_in_with_oauth(found.provider),
        security=SECURITY,
    )


@router.post("/accounts/{account_id}")
async def update_account(
    request: Request, caller: Actor, account_id: str, accounts: Accounts
) -> Response:
    form = await request.form()
    here = f"/ui/accounts/{account_id}"
    changes: dict[str, Any] = {"display_name": None, "rename": False}
    if "display_name" in form:
        changes = {
            "display_name": str(form.get("display_name") or "").strip() or None,
            "rename": True,
        }
    with failing(here):
        existing = accounts.get(caller, account_id)
        settings = _changed(existing.settings, _settings(form), set(form.keys()))
        await accounts.update(
            caller,
            account_id,
            settings=settings,
            credentials=_password(form),
            **changes,
        )
    return back(here, "Saved.")


@router.post("/accounts/{account_id}/verify")
async def verify_account(
    caller: Actor, account_id: str, accounts: Accounts
) -> Response:
    here = f"/ui/accounts/{account_id}"
    with failing(here, "Not reachable: "):
        checked = await accounts.verify(caller, account_id)
    return back(here, f"Signed in to the provider. Status: {checked.status.value}.")


@router.post("/accounts/{account_id}/delete")
async def delete_account(
    caller: Actor, account_id: str, accounts: Accounts
) -> Response:
    with failing(f"/ui/accounts/{account_id}"):
        await accounts.delete(caller, account_id)
    return back("/ui/accounts", "Account removed from the service.")
