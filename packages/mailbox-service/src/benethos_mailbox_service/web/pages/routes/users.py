"""Users and their passwords. A user's tokens are in ``tokens``."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ....common.text import plural
from ....common.urls import path_and_query
from ....data.models import ActivityFilter
from ....domain.rights import Access
from ....domain.users import UserService
from ...services import (
    Passwords,
    Users,
    get_audit,
    get_factors,
    get_passwords,
    get_roles,
    get_tokens,
)
from ..deps import Actor, Viewer, account_names, if_allowed
from ..editor import editor
from ..effective import view_of
from ..filters import Field, filter_bar
from ..forms import REFUSED, failing, text_of
from ..grants import (
    read_grants,
    read_service,
)
from ..session import show_once, take_once
from ..templates import PAGE_SIZE, back, local_path, page_links, render
from . import audit as audit_routes

router = APIRouter()

# The newest activities of a user its page shows.
RECENT = 10


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
        can_batch=caller.allows("update_user"),
        role_choices=roles,
        here=path_and_query(str(request.url)),
    )


@router.post("/users/batch")
async def change_users(
    request: Request,
    caller: Actor,
    users: Users,
    user: Annotated[list[str] | None, Form()] = None,
    action: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "",
    back_to: Annotated[str, Form(alias="back")] = "",
) -> Response:
    """One change to every ticked user: disable, enable, give or take a
    role. What the caller may not do to a user is named, the rest done."""
    here = local_path(back_to, "/ui/users")
    with failing(here):
        done = users.change_users(caller, user or [], action, role or None)
    refused = "; ".join(f"{name}: {why}" for name, why in done.refused)
    message: str | None = f"{plural(len(done.changed), 'user')} changed."
    if not done.changed:
        message = None if refused else "Nothing to change."
    return back(request, here, message, f"Not changed: {refused}." if refused else None)


@router.get("/users/new")
async def new_user(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("create_user")
    return _newuser_page(request, caller)


def _newuser_page(
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


def typed_token(form: Any) -> dict[str, str]:
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
        "/ui/users/new", again=lambda err: _newuser_page(request, caller, form, err)
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
    return user_page(request, caller, user_id, users)


def user_page(
    request: Request,
    caller: Access,
    user_id: str,
    users: UserService,
    *,
    form: Any = None,
    token_form: Any = None,
    err: str | None = None,
) -> HTMLResponse:
    """A user's page, at one of its tabs. With ``form`` its editor shows
    what was typed, on Rights, with ``token_form`` the fields of a new
    token do, on Access."""
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
        typed_token=typed_token(token_form) if token_form is not None else None,
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
        can_remove_device=caller.allows("remove_totp_device"),
        factor=if_allowed(
            caller,
            "get_second_factor",
            lambda: get_factors(request).of(caller, user_id),
            None,
        ),
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
        **_tabs(request, caller, form, token_form),
    )


# The tabs of a user's page (docs/UI.md 6.3).
TABS = (("rights", "Rights"), ("access", "Access"), ("activity", "Activity"))


def _tabs(
    request: Request, caller: Access, form: Any, token_form: Any
) -> dict[str, Any]:
    """The tabs the caller sees and the one shown: the one of a refused
    form, else the one the address names, else Rights."""
    shown = [
        (k, label)
        for k, label in TABS
        if k != "activity" or caller.allows("list_activity")
    ]
    keys = [key for key, _ in shown]
    wanted = request.query_params.get("tab", "")
    tab = wanted if wanted in keys else "rights"
    if form is not None:
        tab = "rights"
    elif token_form is not None:
        tab = "access"
    return {"tabs_shown": shown, "tab": tab}


def access_tab(user_id: str) -> str:
    """The tab of a user's page with its password, factor and tokens."""
    return f"/ui/users/{user_id}?tab=access"


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
        again=lambda err: user_page(
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
    here = access_tab(user_id)
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
    here = access_tab(user_id)
    with failing(here):
        password = await passwords.one_time_password(caller, user_id)
    show_once(request, f"password:{user_id}", password)
    return back(request, here, "One-time password made.")
