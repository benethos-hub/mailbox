"""Users, their passwords and their tokens."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ....common.clock import utc_now
from ....data.models import ActivityFilter
from ....domain.rights import Access
from ....domain.users import UserService
from ...services import (
    Passwords,
    Tokens,
    Users,
    get_audit,
    get_passwords,
    get_roles,
    get_tokens,
)
from ..deps import Actor, Viewer, account_names, if_allowed
from ..editor import REFUSED, editor
from ..effective import view_of
from ..filters import Field, filter_bar
from ..forms import FormError, failing, text_of
from ..grants import (
    read_grants,
    read_service,
)
from ..session import show_once, take_once
from ..templates import PAGE_SIZE, back, page_links, render
from . import audit as audit_routes

router = APIRouter()

# The newest activities of a user its page shows.
RECENT = 10

# Longer than that is a token without an end: leave the field empty for one.
MAX_TOKEN_DAYS = 3650


def _role_choices(request: Request, caller: Access, held: list[str]) -> list[str]:
    """The roles a user may be given: every role the caller sees, and those
    the user holds already, so a save keeps them."""
    known: set[str] = if_allowed(
        caller,
        "list_roles",
        lambda: {role.id for role in get_roles(request).list_roles(caller)},
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
    found = users.page_users(
        caller,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
        name=bar.value("name") or None,
        role=bar.value("role") or None,
        disabled=True if bar.value("disabled") else None,
        ui_sign_in=False if bar.value("api_only") else None,
    )
    return render(
        request,
        "pages/users.html",
        page="users",
        bar=bar,
        users=found.items,
        pages=page_links(request, found.next_cursor),
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
        **editor(request, caller, [], [], form),
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
async def create_user(
    request: Request, caller: Actor, users: Users, passwords: Passwords
) -> Response:
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
            password = await passwords.one_time_password(caller, user.id)
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
    held = get_tokens(request)
    tokens = if_allowed(
        caller, "list_tokens", lambda: held.list_tokens(caller, user_id), None
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
        tokens=[(token, held.token_state(token)) for token in tokens or []],
        can_list_tokens=tokens is not None,
        new_token=take_once(request, f"token:{user_id}"),
        new_password=take_once(request, f"password:{user_id}"),
        sign_in=get_passwords(request).sign_in_state(found),
        role_choices=_role_choices(
            request, caller, [*found.roles, *(typed["roles"] if typed else [])]
        ),
        names=account_names(request, caller),
        is_me=found.id == caller.user_id,
        can_update=caller.allows("update_user"),
        can_delete=caller.allows("delete_user") and found.id != caller.user_id,
        can_create_token=caller.allows("create_token"),
        can_revoke=caller.allows("revoke_token"),
        can_set_password=caller.allows("set_password"),
        can_remove_factor=caller.allows("remove_second_factor"),
        activity=if_allowed(
            caller,
            "list_activity",
            lambda: (
                get_audit(request)
                .list_activity(
                    caller, limit=RECENT, matching=ActivityFilter(user_id=user_id)
                )
                .items
            ),
            None,
        ),
        outcomes=audit_routes.OUTCOMES,
        **editor(request, caller, found.service, found.grants, form),
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
    passwords: Passwords,
    new_password: Annotated[str, Form()] = "",
    repeat_password: Annotated[str, Form()] = "",
) -> Response:
    here = f"/ui/users/{user_id}"
    if new_password != repeat_password:
        return back(request, here, error="The two passwords differ.")
    with failing(here):
        await passwords.set_password(caller, user_id, new_password)
    return back(request, here, "Password set. It must be changed at the next sign-in.")


@router.post("/users/{user_id}/one-time")
async def one_time_password(
    request: Request, caller: Actor, user_id: str, passwords: Passwords
) -> Response:
    """A password the service makes, shown once on the next page."""
    here = f"/ui/users/{user_id}"
    with failing(here):
        password = await passwords.one_time_password(caller, user_id)
    show_once(request, f"password:{user_id}", password)
    return back(request, here, "One-time password made.")


# --- tokens ---------------------------------------------------------------------


@router.post("/users/{user_id}/tokens")
async def create_token(
    request: Request, caller: Actor, user_id: str, users: Users, tokens: Tokens
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
        _, plain = tokens.create_token(caller, user_id, name, expires_at)
    # Shown on the next page, once, and never in the URL.
    show_once(request, f"token:{user_id}", plain)
    return back(request, here)


@router.post("/users/{user_id}/tokens/{token_id}/revoke")
async def revoke_token(
    request: Request, caller: Actor, user_id: str, token_id: str, tokens: Tokens
) -> Response:
    here = f"/ui/users/{user_id}"
    with failing(here):
        token = tokens.revoke_token(caller, user_id, token_id)
    return back(request, here, f"Token {token.name} revoked.")
