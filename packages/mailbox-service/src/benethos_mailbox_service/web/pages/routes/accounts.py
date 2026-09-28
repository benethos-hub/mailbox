"""Accounts: list, connect from the address (docs/UI.md, 6.1), change,
verify, remove."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import SecretStr

from ....data.models import AccountStatus, ProviderType
from ....domain.accounts import AccountService
from ....domain.discovery import connectable, sign_ins
from ....domain.rights import Access
from ....domain.system import StatusService
from ....errors import MailboxServiceError
from ...errors import status_of
from ...services import Accounts, Discoverer, Status, get_oauth
from ..deps import Actor, Viewer
from ..filters import Field, filter_bar
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


def _submitted(form: Any) -> dict[str, str | int | bool | None]:
    """The settings the form sent, ``None`` for a field sent empty. A field
    the form did not send is left out and changes nothing. The domain
    compares them with the stored ones."""
    submitted: dict[str, str | int | bool | None] = dict(_settings(form))
    for key in SETTING_FIELDS:
        if key in form and key not in submitted:
            submitted[key] = None
    return submitted


def _password(form: Any) -> dict[str, SecretStr]:
    value = str(form.get("password") or "")
    return {"password": SecretStr(value)} if value else {}


@router.get("/accounts")
async def list_accounts(
    request: Request, caller: Viewer, accounts: Accounts
) -> HTMLResponse:
    bar = filter_bar(
        request,
        (
            Field(
                "provider",
                "Provider",
                "select",
                [(p.value, p.value) for p in ProviderType],
            ),
            Field(
                "status",
                "Status",
                "select",
                [(s.value, s.value) for s in AccountStatus],
            ),
        ),
        search=Field("address", "Address"),
    )
    problem = ""
    try:
        provider = (
            ProviderType(bar.value("provider")) if bar.value("provider") else None
        )
        status = AccountStatus(bar.value("status")) if bar.value("status") else None
    except ValueError:
        provider, status, problem = None, None, "Filter: unknown provider or status"
    return render(
        request,
        "pages/accounts.html",
        page="accounts",
        bar=bar,
        problem=problem,
        accounts=accounts.list(
            caller,
            address=bar.value("address") or None,
            provider=provider,
            status=status,
        ),
        can_create=caller.allows("create_account"),
    )


@router.get("/accounts/new")
async def new_account(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_account")
    return _connect_page(request, "")


def _connect_page(
    request: Request, email: str, status_code: int = 200, **context: Any
) -> HTMLResponse:
    """The connect page: the address, and what follows from it."""
    context.setdefault("discovery", None)
    context.setdefault("retry", None)
    return render(
        request,
        "pages/account_new.html",
        page="accounts",
        status_code=status_code,
        email=email,
        security=SECURITY,
        oauth_providers=_oauth_providers(request),
        **context,
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
    return _connect_page(
        request,
        email,
        discovery=found,
        usable=connectable(found.candidates),
        sign_ins=sign_ins(found.candidates, _oauth_providers(request)),
    )


@router.post("/accounts")
async def create_account(
    request: Request, caller: Actor, accounts: Accounts
) -> Response:
    """The servers are tried before anything is stored. A refusal shows
    the page again with what was typed, the password left out."""
    form = await request.form()
    email = str(form.get("email") or "").strip()
    settings = _settings(form)
    display_name = str(form.get("display_name") or "").strip()
    try:
        provider = ProviderType(str(form.get("provider") or ProviderType.IMAP))
    except ValueError:
        return back(request, "/ui/accounts/new", error="Unknown provider.")
    try:
        account = await accounts.create(
            caller,
            provider,
            email,
            display_name or None,
            settings,
            _password(form),
        )
    except MailboxServiceError as exc:
        retry = {
            "provider": provider.value,
            "settings": settings,
            "display_name": display_name,
            "error": exc.message,
        }
        return _connect_page(request, email, status_of(exc), retry=retry)
    return back(request, f"/ui/accounts/{account.id}", f"{account.email} connected.")


@router.get("/accounts/{account_id}")
async def account(
    request: Request,
    caller: Viewer,
    account_id: str,
    accounts: Accounts,
    status: Status,
) -> HTMLResponse:
    return _account_page(request, caller, account_id, accounts, status)


def _account_page(
    request: Request,
    caller: Access,
    account_id: str,
    accounts: AccountService,
    status: StatusService,
    form: Any = None,
    err: str | None = None,
) -> HTMLResponse:
    """An account's page. With ``form`` its editor shows what was typed,
    the password left out."""
    found = accounts.get(caller, account_id)
    return render(
        request,
        "pages/account.html",
        page="accounts",
        status_code=400 if err else 200,
        err=err,
        typed=(
            {
                "display_name": str(form.get("display_name") or "").strip(),
                "settings": {
                    key: str(form.get(key) or "").strip() for key in SETTING_FIELDS
                },
            }
            if form is not None
            else None
        ),
        account=found,
        can_read=caller.allows("list_messages", account_id),
        can_audit=caller.allows("list_sends", account_id),
        can_update=caller.allows("update_account", account_id),
        can_verify=caller.allows("verify_account", account_id),
        can_delete=caller.allows("delete_account", account_id),
        signs_in_with_oauth=accounts.signs_in_with_oauth(found.provider),
        security=SECURITY,
        sync=status.sync_of(caller, account_id),
    )


@router.post("/accounts/{account_id}")
async def update_account(
    request: Request,
    caller: Actor,
    account_id: str,
    accounts: Accounts,
    status: Status,
) -> Response:
    form = await request.form()
    here = f"/ui/accounts/{account_id}"
    changes: dict[str, Any] = {"display_name": None, "rename": False}
    if "display_name" in form:
        changes = {
            "display_name": str(form.get("display_name") or "").strip() or None,
            "rename": True,
        }
    with failing(
        here,
        again=lambda err: _account_page(
            request, caller, account_id, accounts, status, form, err
        ),
    ):
        await accounts.update(
            caller,
            account_id,
            settings=_submitted(form),
            credentials=_password(form),
            **changes,
        )
    return back(request, here, "Saved.")


@router.post("/accounts/{account_id}/verify")
async def verify_account(
    request: Request, caller: Actor, account_id: str, accounts: Accounts
) -> Response:
    here = f"/ui/accounts/{account_id}"
    with failing(here, "Not reachable: "):
        checked = await accounts.verify(caller, account_id)
    return back(
        request, here, f"Signed in to the provider. Status: {checked.status.value}."
    )


@router.post("/accounts/{account_id}/delete")
async def delete_account(
    request: Request, caller: Actor, account_id: str, accounts: Accounts
) -> Response:
    with failing(f"/ui/accounts/{account_id}"):
        await accounts.delete(caller, account_id)
    return back(request, "/ui/accounts", "Account removed from the service.")
