"""Users, their tokens, and roles."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....common.clock import utc_now
from ....data.models import ApiToken, Grant, Role
from ....domain import permissions
from ....domain.access import Access
from ....errors import MailboxApiError
from ...services import get_accounts, get_users
from ..deps import Actor, Viewer
from ..grants import GROUP_NAMES, GrantFormError, account_choices, read_grants, rows_of
from ..session import show_once, take_once
from ..templates import back, render

router = APIRouter()


def _account_names(request: Request, caller: Access) -> dict[str, str]:
    """Emails of the accounts the caller sees, to show a grant readably."""
    accounts = get_accounts(request)
    return {account.id: account.email for account in accounts.list(caller)}


def _editor(request: Request, caller: Access, grants: list[Grant]) -> dict[str, Any]:
    """What the grant editor needs."""
    accounts = get_accounts(request)
    rows = rows_of(grants)
    return {
        "rows": rows,
        "account_choices": account_choices(accounts.list(caller), rows),
        "groups": GROUP_NAMES,
        "group_ops": {
            name: ", ".join(permissions.GROUPS.get(name, ("every right",)))
            for name in GROUP_NAMES
        },
    }


def _role_choices(request: Request, caller: Access, held: list[str]) -> list[str]:
    """The roles a user may be given: every role the caller sees, and those
    the user holds already, so a save keeps them."""
    known = (
        {role.id for role in get_users(request).list_roles(caller)}
        if caller.allows("list_roles")
        else set()
    )
    return sorted(known | set(held))


def _state(token: ApiToken) -> str:
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= utc_now():
        return "expired"
    return "active"


# --- users ----------------------------------------------------------------------


@router.get("/users")
async def list_users(request: Request, caller: Viewer) -> HTMLResponse:
    return render(
        request,
        "pages/users.html",
        page="users",
        users=get_users(request).list_users(caller),
        names=_account_names(request, caller),
        can_create=caller.allows("create_user"),
    )


@router.get("/users/new")
async def new_user(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_user")
    return render(
        request,
        "pages/user_new.html",
        page="users",
        role_choices=_role_choices(request, caller, []),
        **_editor(request, caller, []),
    )


@router.post("/users")
async def create_user(request: Request, caller: Actor) -> Response:
    form = await request.form()
    name = str(form.get("name") or "").strip()
    if not name:
        return back("/ui/users/new", error="A user needs a name.")
    try:
        user = get_users(request).create_user(
            caller,
            name,
            [str(role) for role in form.getlist("roles")],
            read_grants(form),
        )
    except (MailboxApiError, GrantFormError) as exc:
        return back("/ui/users/new", error=_message(exc))
    return back(f"/ui/users/{user.id}", f"{user.name} created.")


@router.get("/users/{user_id}")
async def user(request: Request, caller: Viewer, user_id: str) -> HTMLResponse:
    users = get_users(request)
    found = users.get_user(caller, user_id)
    tokens = (
        users.list_tokens(caller, user_id) if caller.allows("list_tokens") else None
    )
    return render(
        request,
        "pages/user.html",
        page="users",
        user=found,
        tokens=[(token, _state(token)) for token in tokens or []],
        can_list_tokens=tokens is not None,
        new_token=take_once(request, f"token:{user_id}"),
        role_choices=_role_choices(request, caller, found.roles),
        names=_account_names(request, caller),
        is_me=found.id == caller.user_id,
        can_update=caller.allows("update_user"),
        can_delete=caller.allows("delete_user") and found.id != caller.user_id,
        can_create_token=caller.allows("create_token"),
        can_revoke=caller.allows("revoke_token"),
        **_editor(request, caller, found.grants),
    )


@router.post("/users/{user_id}")
async def update_user(request: Request, caller: Actor, user_id: str) -> Response:
    form = await request.form()
    here = f"/ui/users/{user_id}"
    try:
        get_users(request).update_user(
            caller,
            user_id,
            name=str(form.get("name") or "").strip() or None,
            roles=[str(role) for role in form.getlist("roles")],
            grants=read_grants(form),
            disabled="disabled" in form,
        )
    except (MailboxApiError, GrantFormError) as exc:
        return back(here, error=_message(exc))
    return back(here, "Saved.")


@router.post("/users/{user_id}/delete")
async def delete_user(request: Request, caller: Actor, user_id: str) -> Response:
    try:
        get_users(request).delete_user(caller, user_id)
    except MailboxApiError as exc:
        return back(f"/ui/users/{user_id}", error=exc.message)
    return back("/ui/users", "User deleted, and its tokens with it.")


# --- tokens ---------------------------------------------------------------------


@router.post("/users/{user_id}/tokens")
async def create_token(request: Request, caller: Actor, user_id: str) -> Response:
    form = await request.form()
    here = f"/ui/users/{user_id}"
    name = str(form.get("name") or "").strip()
    days = str(form.get("days") or "").strip()
    if not name:
        return back(here, error="A token needs a name.")
    if days and not (days.isdigit() and int(days) > 0):
        return back(here, error="Days valid must be a whole number above 0.")
    expires_at = utc_now() + timedelta(days=int(days)) if days else None
    try:
        _, plain = get_users(request).create_token(caller, user_id, name, expires_at)
    except MailboxApiError as exc:
        return back(here, error=exc.message)
    # Shown on the next page, once; never in the URL.
    show_once(request, f"token:{user_id}", plain)
    return back(here)


@router.post("/users/{user_id}/tokens/{token_id}/revoke")
async def revoke_token(
    request: Request, caller: Actor, user_id: str, token_id: str
) -> Response:
    here = f"/ui/users/{user_id}"
    try:
        token = get_users(request).revoke_token(caller, user_id, token_id)
    except MailboxApiError as exc:
        return back(here, error=exc.message)
    return back(here, f"Token {token.name} revoked.")


# --- roles ----------------------------------------------------------------------


@router.get("/roles")
async def list_roles(request: Request, caller: Viewer) -> HTMLResponse:
    users = get_users(request)
    roles = users.list_roles(caller)
    return render(
        request,
        "pages/roles.html",
        page="roles",
        roles=roles,
        used=_used_by(request, caller, roles),
        names=_account_names(request, caller),
        can_create=caller.allows("create_role"),
        **_editor(request, caller, []),
    )


def _used_by(request: Request, caller: Access, roles: list[Role]) -> dict[str, int]:
    """How many users hold each role, if the caller may list users."""
    if not caller.allows("list_users"):
        return {}
    holders = get_users(request).list_users(caller)
    return {role.id: sum(role.id in user.roles for user in holders) for role in roles}


@router.post("/roles")
async def create_role(request: Request, caller: Actor) -> Response:
    form = await request.form()
    role_id = str(form.get("id") or "").strip()
    if not role_id:
        return back("/ui/roles", error="A role needs a name.")
    try:
        role = get_users(request).create_role(caller, role_id, read_grants(form))
    except (MailboxApiError, GrantFormError) as exc:
        return back("/ui/roles", error=_message(exc))
    return back(_role_path(role.id), f"Role {role.id} created.")


@router.get("/roles/{role_id}")
async def role(request: Request, caller: Viewer, role_id: str) -> HTMLResponse:
    found = get_users(request).get_role(caller, role_id)
    holders = (
        [u for u in get_users(request).list_users(caller) if role_id in u.roles]
        if caller.allows("list_users")
        else None
    )
    return render(
        request,
        "pages/role.html",
        page="roles",
        role=found,
        holders=holders,
        names=_account_names(request, caller),
        can_update=caller.allows("replace_role"),
        can_delete=caller.allows("delete_role"),
        **_editor(request, caller, found.grants),
    )


@router.post("/roles/{role_id}")
async def replace_role(request: Request, caller: Actor, role_id: str) -> Response:
    form = await request.form()
    here = _role_path(role_id)
    try:
        get_users(request).replace_role(caller, role_id, read_grants(form))
    except (MailboxApiError, GrantFormError) as exc:
        return back(here, error=_message(exc))
    return back(here, "Saved.")


@router.post("/roles/{role_id}/delete")
async def delete_role(request: Request, caller: Actor, role_id: str) -> Response:
    try:
        get_users(request).delete_role(caller, role_id)
    except MailboxApiError as exc:
        return back(_role_path(role_id), error=exc.message)
    return back("/ui/roles", f"Role {role_id} deleted.")


def _role_path(role_id: str) -> str:
    """A role's page; its name is free text."""
    return f"/ui/roles/{quote(role_id, safe='')}"


def _message(exc: MailboxApiError | GrantFormError) -> str:
    return exc.message if isinstance(exc, MailboxApiError) else str(exc)
