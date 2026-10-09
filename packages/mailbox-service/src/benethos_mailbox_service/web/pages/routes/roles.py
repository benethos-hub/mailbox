"""Roles: the list, the editor of a new one, a role's page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....data.models import Role
from ....domain.rights import Access
from ....domain.users import RoleService
from ...services import Roles
from ..deps import Actor, Viewer, account_names, if_allowed
from ..editor import editor
from ..forms import REFUSED, failing, text_of
from ..grants import ROLE_TEMPLATES, read_grants, read_service, require_recipients
from ..templates import back, render, segment

router = APIRouter()


@router.get("/roles")
async def list_roles(request: Request, caller: Viewer, roles: Roles) -> HTMLResponse:
    found = roles.list_roles(caller)
    return render(
        request,
        "pages/roles.html",
        page="roles",
        roles=found,
        used=_used_by(request, caller, roles, found),
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
        **editor(
            request,
            caller,
            list(chosen.service) if chosen is not None else [],
            list(chosen.grants) if chosen is not None else [],
            form,
        ),
    )


def _used_by(
    request: Request, caller: Access, roles: RoleService, found: list[Role]
) -> dict[str, int]:
    """How many users hold each role, if the caller may list users."""
    return if_allowed(
        caller,
        "list_users",
        lambda: {role.id: len(roles.holders_of(caller, role.id)) for role in found},
        {},
    )


@router.post("/roles")
async def create_role(request: Request, caller: Actor, roles: Roles) -> Response:
    form = await request.form()
    role_id = text_of(form, "id")
    with failing(
        "/ui/roles/new", again=lambda err: _new_role_page(request, caller, form, err)
    ):
        grants = read_grants(form)
        chosen = ROLE_TEMPLATES.get(str(form.get("template") or ""))
        if chosen is not None and chosen.recipients_required:
            require_recipients(grants)
        role = roles.create_role(caller, role_id, grants, read_service(form))
    return back(request, _role_path(role.id), f"Role {role.id} created.")


@router.get("/roles/{role_id}")
async def role(
    request: Request, caller: Viewer, role_id: str, roles: Roles
) -> HTMLResponse:
    return _role_page(request, caller, role_id, roles)


def _role_page(
    request: Request,
    caller: Access,
    role_id: str,
    roles: RoleService,
    form: Any = None,
    err: str | None = None,
) -> HTMLResponse:
    """A role's page. With ``form`` its editor shows what was typed."""
    found = roles.get_role(caller, role_id)
    holders = if_allowed(
        caller, "list_users", lambda: roles.holders_of(caller, role_id), None
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
        **editor(request, caller, found.service, found.grants, form),
    )


@router.post("/roles/{role_id}")
async def replace_role(
    request: Request, caller: Actor, role_id: str, roles: Roles
) -> Response:
    form = await request.form()
    here = _role_path(role_id)
    with failing(
        here,
        again=lambda err: _role_page(request, caller, role_id, roles, form, err),
    ):
        roles.replace_role(caller, role_id, read_grants(form), read_service(form))
    return back(request, here, "Saved.")


@router.post("/roles/{role_id}/delete")
async def delete_role(
    request: Request, caller: Actor, role_id: str, roles: Roles
) -> Response:
    with failing(_role_path(role_id)):
        roles.delete_role(caller, role_id)
    return back(request, "/ui/roles", f"Role {role_id} deleted.")


def _role_path(role_id: str) -> str:
    """A role's page. Its name is free text."""
    return f"/ui/roles/{segment(role_id)}"
