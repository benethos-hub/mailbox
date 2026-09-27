"""Reading mail: every account's inbox together, one account's folders and
messages, a message, its attachments and its original.

Mail is foreign content. A body is shown as text, escaped like everything
else. An HTML-only mail shows as the text made from its HTML, never as
HTML. An attachment or the original is only ever downloaded, never shown
on this origin.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from ....data.mail.text import from_html
from ....data.models import Folder, FolderRole, Message, MessageFilter
from ....domain.access import Access
from ....domain.mailbox import MailboxService, find_folder
from ...responses import download
from ...search import FIELDS, FLAGS, filter_from
from ...services import Mailbox, get_accounts
from ..deps import Viewer, account_of, emails_of
from ..errors import error_page
from ..filters import Field, FilterBar, Kind, filter_bar
from ..forms import first_problem
from ..navigation import mail_trail
from ..rights import mail_rights
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()

# The search of every message list, by the API's query names (web.search).
SEARCH = Field("q", "Search text")
LABELS: dict[str, tuple[str, Kind]] = {
    "from": ("From", "text"),
    "to": ("To", "text"),
    "subject": ("Subject", "text"),
    "after": ("From day", "date"),
    "before": ("Before day", "date"),
    "unread": ("unread", "flag"),
    "starred": ("starred", "flag"),
    "has_attachments": ("with attachments", "flag"),
}
MAIL_FILTERS = tuple(Field(name, label, kind) for name, (label, kind) in LABELS.items())


def mail_bar(
    request: Request,
    extra: tuple[Field, ...] = (),
    keep: list[tuple[str, str]] | None = None,
) -> FilterBar:
    return filter_bar(request, (*extra, *MAIL_FILTERS), search=SEARCH, keep=keep or [])


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


def _readable_accounts(caller: Access, request: Request) -> list[Any]:
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
    accounts = _readable_accounts(caller, request)
    page = await mailbox.list_all_messages(
        caller,
        account_ids=chosen or None,
        folder_role=role,
        search=search,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
    )
    places = (
        Field(
            "folder",
            "Folder",
            "select",
            [(r.value, r.value) for r in FolderRole if r is not FolderRole.INBOX],
            blank=FolderRole.INBOX.value,
        ),
        Field("account", "Accounts", "checks", [(a.id, a.email) for a in accounts]),
    )
    return render(
        request,
        "pages/mail.html",
        page="mail",
        messages=page.items,
        incomplete=page.incomplete,
        pages=page_links(request, page.next_cursor),
        emails=emails_of(accounts),
        chosen=chosen,
        role=role.value,
        bar=mail_bar(request, places),
        fields=fields,
        problem=problem,
    )


# The folder forms of an account's mail page, as a page shows them first:
# a new folder, and the name or parent of the one shown.
FOLDER_FORMS: dict[str, Any] = {
    "new": "",
    "inside": False,
    "name": None,
    "moving": False,
    "parent": None,
}


@router.get("/accounts/{account_id}/mail")
async def account_mail(
    request: Request, caller: Viewer, account_id: str, mailbox: Mailbox
) -> HTMLResponse:
    """One folder of one account, beside the account's folders."""
    wanted = request.query_params.get("folder") or FolderRole.INBOX.value
    return await account_mail_page(request, caller, account_id, mailbox, wanted)


async def account_mail_page(
    request: Request,
    caller: Access,
    account_id: str,
    mailbox: MailboxService,
    wanted: str,
    typed: dict[str, Any] | None = None,
    err: str | None = None,
) -> HTMLResponse:
    """The folder ``wanted`` of one account. With ``typed`` a folder form
    shows what was typed (see ``FOLDER_FORMS``) and ``err`` why it was
    refused."""
    account = account_of(request, caller, account_id)
    folders = await mailbox.list_folders(caller, account_id)
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
        status_code=400 if err else 200,
        err=err,
        typed={**FOLDER_FORMS, **(typed or {})},
        account=account,
        tree=_tree(folders),
        current=current,
        trail=[*mail_trail(account), (_counted(current), None)],
        bar=mail_bar(request, keep=[("folder", current.id)]),
        messages=page.items,
        pages=page_links(request, page.next_cursor),
        fields=fields,
        problem=problem,
        can=can,
        selectable=can["change"] or can["trash"] or can["purge"],
        here=(
            str(request.url.path)
            + (f"?{request.url.query}" if request.url.query else "")
            if request.method == "GET"
            else f"/ui/accounts/{account_id}/mail?{urlencode({'folder': current.id})}"
        ),
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
    names = {f.id: f.name for f in folders}
    folder = found.folder_ids[0] if found.folder_ids else None
    trail = mail_trail(account, (folder, names.get(folder, folder)) if folder else None)
    return render(
        request,
        "pages/message.html",
        page="mail",
        account=account,
        trail=[*trail, (found.subject or "(no subject)", None)],
        back_to=trail[-1][1],
        message=found,
        body=_body(found),
        from_html=not found.text_body and bool(found.html_body),
        tree=_tree(folders),
        in_trash=any(
            f.role is FolderRole.TRASH for f in folders if f.id in found.folder_ids
        ),
        can=mail_rights(caller, account_id),
        can_raw=caller.allows("get_message_raw", account_id),
        can_attachment=caller.allows("get_attachment", account_id),
    )


def _counted(folder: Folder) -> str:
    """A folder's name with how many messages it holds."""
    if folder.total is None:
        return folder.name
    unread = f", {folder.unread} unread" if folder.unread else ""
    return f"{folder.name} · {folder.total} messages{unread}"


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
