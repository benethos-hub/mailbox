"""Reading mail: every account's inbox together, one account's folders and
messages, a message, its attachments and its original.

Mail is foreign content. A body is shown as text, escaped like everything
else; an HTML-only mail as the text made from its HTML, never as HTML. An
attachment or the original is only ever downloaded, never shown on this
origin.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from ....data.mail.text import from_html
from ....data.models import Folder, FolderRole, Message, MessageFilter
from ....domain.access import Access
from ...services import get_accounts, get_mailbox
from ..deps import Viewer, account_of
from ..errors import error_page
from ..templates import render

router = APIRouter()

PAGE_SIZE = 50
# The search form: its fields and the filter each fills.
SEARCH_FIELDS = ("q", "sender", "subject", "after", "before")
SEARCH_FLAGS = ("unread", "starred", "has_attachments")


def _search(request: Request) -> tuple[MessageFilter | None, dict[str, str], str]:
    """The filter the query asks for, the fields to fill the form with again,
    and what was wrong with it."""
    query = request.query_params
    fields = {
        k: query[k].strip() for k in (*SEARCH_FIELDS, *SEARCH_FLAGS) if k in query
    }
    fields = {k: v for k, v in fields.items() if v}
    wanted: dict[str, Any] = {
        ("text" if k == "q" else k): v for k, v in fields.items() if k in SEARCH_FIELDS
    }
    wanted.update({k: True for k in SEARCH_FLAGS if k in fields})
    if not wanted:
        return None, fields, ""
    try:
        return MessageFilter(**wanted), fields, ""
    except ValidationError as exc:
        problem = exc.errors()[0]
        return None, fields, f"Search: {problem['loc'][0]}: {problem['msg']}"


def _pages(request: Request, cursor: str | None) -> tuple[str | None, str | None]:
    """Links to the next page (this query with the next cursor) and, from a
    later page, back to the first."""
    query = [(k, v) for k, v in request.query_params.multi_items() if k != "cursor"]
    here = request.url.path
    more = f"{here}?{urlencode([*query, ('cursor', cursor)])}" if cursor else None
    first = f"{here}?{urlencode(query)}" if "cursor" in request.query_params else None
    return more, first


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
    accounts = get_accounts(request)
    return [
        account
        for account in accounts.list(caller)
        if caller.allows("list_all_messages", account.id)
    ]


@router.get("/mail")
async def all_mail(request: Request, caller: Viewer) -> HTMLResponse:
    """Every account's messages of one role, newest first."""
    search, fields, problem = _search(request)
    role_name = request.query_params.get("folder") or FolderRole.INBOX.value
    try:
        role = FolderRole(role_name)
    except ValueError:
        role, problem = FolderRole.INBOX, f"Unknown folder: {role_name}"
    chosen = request.query_params.getlist("account")
    accounts = _readable(caller, request)
    page = await get_mailbox(request).list_all_messages(
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
        pages=_pages(request, page.next_cursor),
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
    request: Request, caller: Viewer, account_id: str
) -> HTMLResponse:
    """One folder of one account, beside the account's folders."""
    account = account_of(request, caller, account_id)
    mailbox = get_mailbox(request)
    folders = await mailbox.list_folders(caller, account_id)
    wanted = request.query_params.get("folder") or FolderRole.INBOX.value
    current = next(
        (f for f in folders if f.id == wanted or (f.role and f.role.value == wanted)),
        None,
    )
    if current is None:
        return error_page(request, 404, f"The account has no folder {wanted}.")
    search, fields, problem = _search(request)
    can = _rights(caller, account_id)
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
        pages=_pages(request, page.next_cursor),
        fields=fields,
        problem=problem,
        can=can,
        selectable=can["change"] or can["trash"] or can["purge"],
        here=str(request.url.path)
        + (f"?{request.url.query}" if request.url.query else ""),
    )


def _rights(caller: Access, account_id: str) -> dict[str, bool]:
    """What the mail pages offer, by the caller's rights on the account."""
    allowed = caller.operations_on(account_id)
    return {
        "write": "send_message" in allowed or "create_draft" in allowed,
        "send": "send_message" in allowed,
        "drafts": "list_drafts" in allowed,
        "change": "update_message" in allowed,
        "trash": "delete_message" in allowed,
        "purge": "delete_message_permanent" in allowed,
        "create_folder": "create_folder" in allowed,
        "update_folder": "update_folder" in allowed,
        "delete_folder": "delete_folder" in allowed,
        "batch": "batch_messages" in allowed,
    }


@router.get("/accounts/{account_id}/mail/{message_id}")
async def message(
    request: Request, caller: Viewer, account_id: str, message_id: str
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    found = await get_mailbox(request).get_message(caller, account_id, message_id)
    folders = (
        await get_mailbox(request).list_folders(caller, account_id)
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
        can=_rights(caller, account_id),
        can_raw=caller.allows("get_message_raw", account_id),
        can_attachment=caller.allows("get_attachment", account_id),
    )


def _body(message: Message) -> str:
    if message.text_body:
        return message.text_body
    return from_html(message.html_body) if message.html_body else ""


@router.get("/accounts/{account_id}/mail/{message_id}/raw")
async def raw(
    request: Request, caller: Viewer, account_id: str, message_id: str
) -> Response:
    data = await get_mailbox(request).get_raw(caller, account_id, message_id)
    return _download(data, f"{message_id}.eml", "message/rfc822")


@router.get("/accounts/{account_id}/mail/{message_id}/attachments/{attachment_id}")
async def attachment(
    request: Request,
    caller: Viewer,
    account_id: str,
    message_id: str,
    attachment_id: str,
) -> Response:
    found = await get_mailbox(request).get_attachment(
        caller, account_id, message_id, attachment_id
    )
    # Never rendered here, whatever type the sender claims.
    return _download(
        found.data, found.filename or attachment_id, "application/octet-stream"
    )


def _download(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
