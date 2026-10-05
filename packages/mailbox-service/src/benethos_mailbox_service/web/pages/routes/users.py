"""Users, their tokens, and roles."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ....common.clock import utc_now
from ....data.models import Grant, Role
from ....domain.rights import Access
from ....domain.users import UserService
from ...services import Users, get_accounts, get_users
from ..deps import Actor, Viewer, account_names, if_allowed
from ..effective import view_of
from ..filters import Field, filter_bar
from ..forms import FormError, failing, text_of
from ..grants import (
    GROUP_NAMES,
    GROUP_SECTIONS,
    ROLE_TEMPLATES,
    SERVICE_NAMES,
    GrantRow,
    ServiceRow,
    account_choices,
    group_hint,
    read_grants,
    read_service,
    require_recipients,
    rows_of,
    service_hint,
    service_of,
    typed_rows,
    typed_service,
)
from ..session import show_once, take_once
from ..templates import back, render, segment

router = APIRouter()

# Longer than that is a token without an end: leave the field empty for one.
MAX_TOKEN_DAYS = 3650


# A refused editor comes back with this status, what was typed, the reason.
REFUSED = 400


def _editor(
    request: Request,
    caller: Access,
    service: list[str],
    grants: list[Grant],
    form: Any = None,
) -> dict[str, Any]:
    """What the editor of rights needs: the service rights and the grant
    rows, as ``form`` held them, else those of ``service`` and ``grants``."""
    accounts = get_accounts(request)
    rows: list[GrantRow] = typed_rows(form) if form is not None else rows_of(grants)
    held: ServiceRow = typed_service(form) if form is not None else service_of(service)
    return {
        "service": held,
        "service_names": SERVICE_NAMES,
        "rows": rows,
        "account_choices": account_choices(accounts.list(caller), rows),
        "groups": GROUP_SECTIONS,
        "group_ops": {name: group_hint(name) for name in GROUP_NAMES},
        "service_ops": {name: service_hint(name) for name in SERVICE_NAMES},
    }


def _role_choices(request: Request, caller: Access, held: list[str]) -> list[str]:
    """The roles a user may be given: every role the caller sees, and those
    the user holds already, so a save keeps them."""
    known: set[str] = if_allowed(
        caller,
        "list_roles",
        lambda: {role.id for role in get_users(request).list_roles(caller)},
        set(),
    )
    return sorted(known | set(held))


# --- users ----------------------------------------------------------------------


@router.get("/users")
async def list_users(request: Request, caller: Viewer, users: Users) -> HTMLResponse:
    roles = _role_choices(request, caller, [])
    bar = filter_bar(
        request,
        (
            Field("role", "Role", "select", [(r, r) for r in roles]),
            Field("disabled", "disabled", "flag"),
            Field("api_only", "API only", "flag"),
        ),
        search=Field("name", "Name"),
    )
    return render(
        request,
        "pages/users.html",
        page="users",
        bar=bar,
        users=users.list_users(
            caller,
            name=bar.value("name") or None,
            role=bar.value("role") or None,
            disabled=True if bar.value("disabled") else None,
            ui_sign_in=False if bar.value("api_only") else None,
        ),
        names=account_names(request, caller),
        can_create=caller.allows("create_user"),
    )


@router.get("/users/new")
async def new_user(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_user")
    return _new_user_page(request, caller)


def _new_user_page(
    request: Request, caller: Access, form: Any = None, err: str | None = None
) -> HTMLResponse:
    """The editor of a new user, empty or as ``form`` held it."""
    typed = _typed_user(form) if form is not None else None
    return render(
        request,
        "pages/user_new.html",
        page="users",
        status_code=REFUSED if err else 200,
        err=err,
        typed=typed,
        role_choices=_role_choices(request, caller, typed["roles"] if typed else []),
        can_set_password=caller.allows("set_password"),
        **_editor(request, caller, [], [], form),
    )


def _typed_user(form: Any) -> dict[str, Any]:
    """The fields of a user's editor as they were submitted."""
    return {
        "name": text_of(form, "name"),
        "roles": [str(role) for role in form.getlist("roles")],
        "signs_in_to": str(form.get("signs_in_to") or "api"),
        "one_time": "one_time" in form,
        "ui_sign_in": "ui_sign_in" in form,
        "disabled": "disabled" in form,
    }


def _typed_token(form: Any) -> dict[str, str]:
    """The fields of a new token as they were submitted."""
    return {
        "name": text_of(form, "name"),
        "days": text_of(form, "days"),
    }


@router.post("/users")
async def create_user(request: Request, caller: Actor, users: Users) -> Response:
    form = await request.form()
    typed = _typed_user(form)
    ui_sign_in = typed["signs_in_to"] == "ui"
    with failing(
        "/ui/users/new", again=lambda err: _new_user_page(request, caller, form, err)
    ):
        user = users.create_user(
            caller,
            typed["name"],
            typed["roles"],
            read_grants(form),
            service=read_service(form),
            ui_sign_in=ui_sign_in,
        )
    here = f"/ui/users/{user.id}"
    if ui_sign_in and typed["one_time"]:
        with failing(here, f"{user.name} created, but no password: "):
            password = await users.one_time_password(caller, user.id)
        # Shown on the next page, once, and never in the URL.
        show_once(request, f"password:{user.id}", password)
    return back(request, here, f"{user.name} created.")


@router.get("/users/{user_id}")
async def user(
    request: Request, caller: Viewer, user_id: str, users: Users
) -> HTMLResponse:
    return _user_page(request, caller, user_id, users)


def _user_page(
    request: Request,
    caller: Access,
    user_id: str,
    users: UserService,
    *,
    form: Any = None,
    token_form: Any = None,
    err: str | None = None,
) -> HTMLResponse:
    """A user's page. With ``form`` its editor shows what was typed, with
    ``token_form`` the fields of a new token do."""
    found = users.get_user(caller, user_id)
    typed = _typed_user(form) if form is not None else None
    tokens = if_allowed(
        caller, "list_tokens", lambda: users.list_tokens(caller, user_id), None
    )
    return render(
        request,
        "pages/user.html",
        page="users",
        status_code=REFUSED if err else 200,
        err=err,
        typed=typed,
        typed_token=_typed_token(token_form) if token_form is not None else None,
        user=found,
        effective=view_of(users.rights_of(caller, user_id)),
        tokens=[(token, users.token_state(token)) for token in tokens or []],
        can_list_tokens=tokens is not None,
        new_token=take_once(request, f"token:{user_id}"),
        new_password=take_once(request, f"password:{user_id}"),
        last_sign_in=users.last_sign_in(caller, user_id),
        role_choices=_role_choices(
            request, caller, [*found.roles, *(typed["roles"] if typed else [])]
        ),
        names=account_names(request, caller),
        is_me=found.id == caller.user_id,
        can_update=caller.allows("update_user"),
        can_delete=caller.allows("delete_user") and found.id != caller.user_id,
        can_create_token=caller.allows("create_token"),
        can_revoke=caller.allows("revoke_token"),
        has_password=users.has_password(caller, user_id),
        can_set_password=caller.allows("set_password"),
        **_editor(request, caller, found.service, found.grants, form),
    )


@router.post("/users/{user_id}")
async def update_user(
    request: Request, caller: Actor, user_id: str, users: Users
) -> Response:
    form = await request.form()
    here = f"/ui/users/{user_id}"
    typed = _typed_user(form)
    # The tick box of the UI sign-in changes something only where the page
    # showed it: not on the own page, since nobody takes its own sign-in.
    ui_sign_in = typed["ui_sign_in"] if "ui_sign_in_shown" in form else None
    with failing(
        here,
        again=lambda err: _user_page(
            request, caller, user_id, users, form=form, err=err
        ),
    ):
        users.update_user(
            caller,
            user_id,
            name=typed["name"] or None,
            roles=typed["roles"],
            service=read_service(form),
            grants=read_grants(form),
            disabled=typed["disabled"],
            ui_sign_in=ui_sign_in,
        )
    return back(request, here, "Saved.")


@router.post("/users/{user_id}/delete")
async def delete_user(
    request: Request, caller: Actor, user_id: str, users: Users
) -> Response:
    with failing(f"/ui/users/{user_id}"):
        users.delete_user(caller, user_id)
    return back(request, "/ui/users", "User deleted, and its tokens with it.")


# --- password -------------------------------------------------------------------


@router.post("/users/{user_id}/password")
async def set_password(
    request: Request,
    caller: Actor,
    user_id: str,
    users: Users,
    new_password: Annotated[str, Form()] = "",
    repeat_password: Annotated[str, Form()] = "",
) -> Response:
    here = f"/ui/users/{user_id}"
    if new_password != repeat_password:
        return back(request, here, error="The two passwords differ.")
    with failing(here):
        await users.set_password(caller, user_id, new_password)
    return back(request, here, "Password set. It must be changed at the next sign-in.")


@router.post("/users/{user_id}/one-time")
async def one_time_password(
    request: Request, caller: Actor, user_id: str, users: Users
) -> Response:
    """A password the service makes, shown once on the next page."""
    here = f"/ui/users/{user_id}"
    with failing(here):
        password = await users.one_time_password(caller, user_id)
    show_once(request, f"password:{user_id}", password)
    return back(request, here, "One-time password made.")


# --- tokens ---------------------------------------------------------------------


@router.post("/users/{user_id}/tokens")
async def create_token(
    request: Request, caller: Actor, user_id: str, users: Users
) -> Response:
    form = await request.form()
    here = f"/ui/users/{user_id}"
    typed = _typed_token(form)
    name, days = typed["name"], typed["days"]
    with failing(
        here,
        again=lambda err: _user_page(
            request, caller, user_id, users, token_form=form, err=err
        ),
    ):
        if days and not (days.isdigit() and 1 <= int(days) <= MAX_TOKEN_DAYS):
            raise FormError(
                f"Days valid must be a whole number from 1 to {MAX_TOKEN_DAYS}."
            )
        expires_at = utc_now() + timedelta(days=int(days)) if days else None
        _, plain = users.create_token(caller, user_id, name, expires_at)
    # Shown on the next page, once, and never in the URL.
    show_once(request, f"token:{user_id}", plain)
    return back(request, here)


@router.post("/users/{user_id}/tokens/{token_id}/revoke")
async def revoke_token(
    request: Request, caller: Actor, user_id: str, token_id: str, users: Users
) -> Response:
    here = f"/ui/users/{user_id}"
    with failing(here):
        token = users.revoke_token(caller, user_id, token_id)
    return back(request, here, f"Token {token.name} revoked.")


# --- roles ----------------------------------------------------------------------


@router.get("/roles")
async def list_roles(request: Request, caller: Viewer, users: Users) -> HTMLResponse:
    roles = users.list_roles(caller)
    return render(
        request,
        "pages/roles.html",
        page="roles",
        roles=roles,
        used=_used_by(request, caller, roles),
        names=account_names(request, caller),
        can_create=caller.allows("create_role"),
    )


@router.get("/roles/new")
async def new_role(
    request: Request, caller: Viewer, template: str = ""
) -> HTMLResponse:
    """The editor of a new role, empty or filled from a template. It takes
    the path of a role named "new", whose page the UI then cannot open:
    the API still can."""
    caller.require("create_role")
    return _new_role_page(request, caller, template=template)


def _new_role_page(
    request: Request,
    caller: Access,
    form: Any = None,
    err: str | None = None,
    template: str = "",
) -> HTMLResponse:
    """The editor of a new role: empty, filled from ``template``, or as
    ``form`` held it."""
    if form is not None:
        template = str(form.get("template") or "")
    chosen = ROLE_TEMPLATES.get(template)
    if form is not None:
        typed_id = text_of(form, "id")
    else:
        typed_id = chosen.id if chosen is not None else ""
    return render(
        request,
        "pages/role_new.html",
        page="roles",
        status_code=REFUSED if err else 200,
        err=err,
        typed_id=typed_id,
        templates=ROLE_TEMPLATES.values(),
        chosen=chosen,
        **_editor(
            request,
            caller,
            list(chosen.service) if chosen is not None else [],
            list(chosen.grants) if chosen is not None else [],
            form,
        ),
    )


def _used_by(request: Request, caller: Access, roles: list[Role]) -> dict[str, int]:
    """How many users hold each role, if the caller may list users."""
    users = get_users(request)
    return if_allowed(
        caller,
        "list_users",
        lambda: {role.id: len(users.holders_of(caller, role.id)) for role in roles},
        {},
    )


@router.post("/roles")
async def create_role(request: Request, caller: Actor, users: Users) -> Response:
    form = await request.form()
    role_id = text_of(form, "id")
    with failing(
        "/ui/roles/new", again=lambda err: _new_role_page(request, caller, form, err)
    ):
        grants = read_grants(form)
        chosen = ROLE_TEMPLATES.get(str(form.get("template") or ""))
        if chosen is not None and chosen.recipients_required:
            require_recipients(grants)
        role = users.create_role(caller, role_id, grants, read_service(form))
    return back(request, _role_path(role.id), f"Role {role.id} created.")


@router.get("/roles/{role_id}")
async def role(
    request: Request, caller: Viewer, role_id: str, users: Users
) -> HTMLResponse:
    return _role_page(request, caller, role_id, users)


def _role_page(
    request: Request,
    caller: Access,
    role_id: str,
    users: UserService,
    form: Any = None,
    err: str | None = None,
) -> HTMLResponse:
    """A role's page. With ``form`` its editor shows what was typed."""
    found = users.get_role(caller, role_id)
    holders = if_allowed(
        caller, "list_users", lambda: users.holders_of(caller, role_id), None
    )
    return render(
        request,
        "pages/role.html",
        page="roles",
        status_code=REFUSED if err else 200,
        err=err,
        role=found,
        holders=holders,
        names=account_names(request, caller),
        can_update=caller.allows("replace_role"),
        can_delete=caller.allows("delete_role"),
        **_editor(request, caller, found.service, found.grants, form),
    )


@router.post("/roles/{role_id}")
async def replace_role(
    request: Request, caller: Actor, role_id: str, users: Users
) -> Response:
    form = await request.form()
    here = _role_path(role_id)
    with failing(
        here,
        again=lambda err: _role_page(request, caller, role_id, users, form, err),
    ):
        users.replace_role(caller, role_id, read_grants(form), read_service(form))
    return back(request, here, "Saved.")


@router.post("/roles/{role_id}/delete")
async def delete_role(
    request: Request, caller: Actor, role_id: str, users: Users
) -> Response:
    with failing(_role_path(role_id)):
        users.delete_role(caller, role_id)
    return back(request, "/ui/roles", f"Role {role_id} deleted.")


def _role_path(role_id: str) -> str:
    """A role's page. Its name is free text."""
    return f"/ui/roles/{segment(role_id)}"
