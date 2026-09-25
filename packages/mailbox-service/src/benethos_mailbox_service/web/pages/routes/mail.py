"""Reading mail: every account's inbox together, one account's folders and
messages, a message, its attachments and its original.

Mail is foreign content. A body is shown as text, escaped like everything
else. An HTML-only mail shows as the text made from its HTML, never as
HTML. An attachment or the original is only ever downloaded, never shown
on this origin.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from ....data.mail.text import from_html
from ....data.models import Folder, FolderRole, Message, MessageFilter
from ....domain.access import Access
from ....domain.mailbox import find_folder
from ...responses import download
from ...search import FIELDS, FLAGS, filter_from
from ...services import Mailbox, get_accounts
from ..deps import Viewer, account_of
from ..errors import error_page
from ..forms import first_problem
from ..rights import mail_rights
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()


def _search(request: Request) -> tuple[MessageFilter | None, dict[str, str], str]:
    """The filter the query asks for, the fields to fill the form with again,
    and what was wrong with it."""
    query = request.query_params
    fields = {k: query[k].strip() for k in (*FIELDS, *FLAGS) if k in query}
    fields = {k: v for k, v in fields.items() if v}
    try:
        return filter_from(fields), fields, ""
    except ValidationError as exc:
        return None, fields, f"Search: {first_problem(exc)}"


def _tree(folders: list[Folder]) -> list[tuple[Folder, int]]:
    """Folders in tree order, each with its depth."""
    children: dict[str | None, list[Folder]] = {}
    ids = {folder.id for folder in folders}
    for folder in folders:
        parent = folder.parent_id if folder.parent_id in ids else None
        children.setdefault(parent, []).append(folder)
    order = list(FolderRole)

    def key(folder: Folder) -> tuple[int, str]:
        rank = order.index(folder.role) if folder.role is not None else len(order)
        return rank, folder.name.lower()

    result: list[tuple[Folder, int]] = []

    def walk(parent: str | None, depth: int) -> None:
        for folder in sorted(children.get(parent, []), key=key):
            result.append((folder, depth))
            walk(folder.id, depth + 1)

    walk(None, 0)
    return result


def _readable(caller: Access, request: Request) -> list[Any]:
    return get_accounts(request).list(caller, may="list_all_messages")


@router.get("/mail")
async def all_mail(request: Request, caller: Viewer, mailbox: Mailbox) -> HTMLResponse:
    """Every account's messages of one role, newest first."""
    search, fields, problem = _search(request)
    role_name = request.query_params.get("folder") or FolderRole.INBOX.value
    try:
        role = FolderRole(role_name)
    except ValueError:
        role, problem = FolderRole.INBOX, f"Unknown folder: {role_name}"
    chosen = request.query_params.getlist("account")
    accounts = _readable(caller, request)
    page = await mailbox.list_all_messages(
        caller,
        account_ids=chosen or None,
        folder_role=role,
        search=search,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
    )
    return render(
        request,
        "pages/mail.html",
        page="mail",
        messages=page.items,
        incomplete=page.incomplete,
        pages=page_links(request, page.next_cursor),
        accounts=accounts,
        emails={account.id: account.email for account in accounts},
        chosen=chosen,
        keep=[("folder", role.value), *(("account", a) for a in chosen)],
        roles=[r.value for r in FolderRole],
        role=role.value,
        fields=fields,
        problem=problem,
    )


@router.get("/accounts/{account_id}/mail")
async def account_mail(
    request: Request, caller: Viewer, account_id: str, mailbox: Mailbox
) -> HTMLResponse:
    """One folder of one account, beside the account's folders."""
    account = account_of(request, caller, account_id)
    folders = await mailbox.list_folders(caller, account_id)
    wanted = request.query_params.get("folder") or FolderRole.INBOX.value
    current = find_folder(folders, wanted)
    if current is None:
        return error_page(request, 404, f"The account has no folder {wanted}.")
    search, fields, problem = _search(request)
    can = mail_rights(caller, account_id)
    can.update(
        change=can["change"] and can["batch"],
        trash=can["trash"] and can["batch"],
        purge=can["purge"] and can["batch"],
    )
    page = await mailbox.list_messages(
        caller,
        account_id,
        folder_id=current.id,
        search=search,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
    )
    return render(
        request,
        "pages/account_mail.html",
        page="mail",
        account=account,
        tree=_tree(folders),
        current=current,
        keep=[("folder", current.id)],
        messages=page.items,
        pages=page_links(request, page.next_cursor),
        fields=fields,
        problem=problem,
        can=can,
        selectable=can["change"] or can["trash"] or can["purge"],
        here=str(request.url.path)
        + (f"?{request.url.query}" if request.url.query else ""),
    )


@router.get("/accounts/{account_id}/mail/{message_id}")
async def message(
    request: Request, caller: Viewer, account_id: str, message_id: str, mailbox: Mailbox
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    found = await mailbox.get_message(caller, account_id, message_id)
    folders = (
        await mailbox.list_folders(caller, account_id)
        if caller.allows("list_folders", account_id)
        else []
    )
    return render(
        request,
        "pages/message.html",
        page="mail",
        account=account,
        message=found,
        body=_body(found),
        from_html=not found.text_body and bool(found.html_body),
        folder_names={f.id: f.name for f in folders},
        tree=_tree(folders),
        in_trash=any(
            f.role is FolderRole.TRASH for f in folders if f.id in found.folder_ids
        ),
        can=mail_rights(caller, account_id),
        can_raw=caller.allows("get_message_raw", account_id),
        can_attachment=caller.allows("get_attachment", account_id),
    )


def _body(message: Message) -> str:
    if message.text_body:
        return message.text_body
    return from_html(message.html_body) if message.html_body else ""


@router.get("/accounts/{account_id}/mail/{message_id}/raw")
async def raw(
    caller: Viewer, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    data = await mailbox.get_raw(caller, account_id, message_id)
    return download(data, f"{message_id}.eml", "message/rfc822")


@router.get("/accounts/{account_id}/mail/{message_id}/attachments/{attachment_id}")
async def attachment(
    caller: Viewer,
    account_id: str,
    message_id: str,
    attachment_id: str,
    mailbox: Mailbox,
) -> Response:
    found = await mailbox.get_attachment(caller, account_id, message_id, attachment_id)
    # Never rendered here, whatever type the sender claims.
    return download(
        found.data, found.filename or attachment_id, "application/octet-stream"
    )
