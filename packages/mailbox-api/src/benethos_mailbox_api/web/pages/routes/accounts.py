"""Accounts: list, connect through autodiscovery, change, verify, delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import SecretStr

from ....data.models import Candidate, ProviderType
from ....domain.accounts import AccountService
from ....domain.discovery import DiscoveryService
from ....errors import MailboxApiError
from ..deps import Actor, Viewer
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


def _service(request: Request) -> AccountService:
    accounts: AccountService = request.app.state.accounts
    return accounts


def _settings(form: Any) -> dict[str, str | int | bool]:
    """The filled-in connection fields; empty ones are left out."""
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
async def list_accounts(request: Request, caller: Viewer) -> HTMLResponse:
    return render(
        request,
        "pages/accounts.html",
        page="accounts",
        accounts=_service(request).list(caller),
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
    )


@router.post("/accounts/discover")
async def discover(request: Request, caller: Actor) -> Response:
    """The ways to connect an address. A POST, so the address stays out of
    access logs, answered with the page itself: a lookup changes nothing."""
    form = await request.form()
    email = str(form.get("email") or "").strip()
    discovery: DiscoveryService = request.app.state.discovery
    try:
        found = await discovery.discover(caller, email)
    except MailboxApiError as exc:
        return back("/ui/accounts/new", error=exc.message)
    return render(
        request,
        "pages/account_new.html",
        page="accounts",
        email=email,
        discovery=found,
        usable=[c for c in found.candidates if _usable(c)],
        security=SECURITY,
    )


def _usable(candidate: Candidate) -> bool:
    """What this service can connect today: IMAP with a password."""
    return candidate.provider is ProviderType.IMAP and candidate.credential in (
        "password",
        "app_password",
    )


@router.post("/accounts")
async def create_account(request: Request, caller: Actor) -> Response:
    form = await request.form()
    email = str(form.get("email") or "").strip()
    settings = _settings(form)
    settings.setdefault("username", email)
    try:
        provider = ProviderType(str(form.get("provider") or ProviderType.IMAP))
    except ValueError:
        return back("/ui/accounts/new", error="Unknown provider.")
    try:
        account = await _service(request).create(
            caller,
            provider,
            email,
            str(form.get("display_name") or "").strip() or None,
            settings,
            _password(form),
        )
    except MailboxApiError as exc:
        return back("/ui/accounts/new", error=f"{email}: {exc.message}")
    return back(f"/ui/accounts/{account.id}", f"{account.email} connected.")


@router.get("/accounts/{account_id}")
async def account(request: Request, caller: Viewer, account_id: str) -> HTMLResponse:
    return render(
        request,
        "pages/account.html",
        page="accounts",
        account=_service(request).get(caller, account_id),
        can_update=caller.allows("update_account", account_id),
        can_verify=caller.allows("verify_account", account_id),
        can_delete=caller.allows("delete_account", account_id),
        security=SECURITY,
    )


@router.post("/accounts/{account_id}")
async def update_account(request: Request, caller: Actor, account_id: str) -> Response:
    form = await request.form()
    here = f"/ui/accounts/{account_id}"
    changes: dict[str, Any] = {"display_name": None, "rename": False}
    if "display_name" in form:
        changes = {
            "display_name": str(form.get("display_name") or "").strip() or None,
            "rename": True,
        }
    try:
        existing = _service(request).get(caller, account_id)
        settings = _changed(existing.settings, _settings(form), set(form.keys()))
        if "username" in settings and settings["username"] is None:
            settings["username"] = existing.email  # as the hint says
        await _service(request).update(
            caller,
            account_id,
            settings=settings,
            credentials=_password(form),
            **changes,
        )
    except MailboxApiError as exc:
        return back(here, error=exc.message)
    return back(here, "Saved.")


@router.post("/accounts/{account_id}/verify")
async def verify_account(request: Request, caller: Actor, account_id: str) -> Response:
    here = f"/ui/accounts/{account_id}"
    try:
        checked = await _service(request).verify(caller, account_id)
    except MailboxApiError as exc:
        return back(here, error=f"Not reachable: {exc.message}")
    return back(here, f"Signed in to the provider. Status: {checked.status.value}.")


@router.post("/accounts/{account_id}/delete")
async def delete_account(request: Request, caller: Actor, account_id: str) -> Response:
    try:
        await _service(request).delete(caller, account_id)
    except MailboxApiError as exc:
        return back(f"/ui/accounts/{account_id}", error=exc.message)
    return back("/ui/accounts", "Account removed from the service.")
