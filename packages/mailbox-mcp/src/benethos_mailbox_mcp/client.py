"""The one place that talks to the Mailbox Service: its paths, the shapes it
takes and the shapes it answers with.

The tools in ``server`` name what they want in their own terms. This
module turns that into requests and the answers into small records, so
nothing above it spells out a path, a query name or a field of the API.
"""

from __future__ import annotations

import codecs
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote

import httpx

from .errors import ApiError, ServiceUnavailableError

DEFAULT_URL = "http://127.0.0.1:8080"
URL_ENV = "MAILBOX_SERVICE_URL"
TOKEN_ENV = "MAILBOX_SERVICE_TOKEN"

# An address with an optional display name.
Recipient = tuple[str, str | None]


@dataclass(frozen=True)
class Attachment:
    """An attachment's bytes, as far as the caller's limit allowed: with
    ``complete`` False, ``data`` stops at that limit."""

    data: bytes
    content_type: str
    charset: str | None  # one Python knows, else None
    filename: str | None
    complete: bool = True


@dataclass(frozen=True)
class MeAccount:
    id: str
    email: str
    display_name: str | None
    operations: frozenset[str]
    warnings: frozenset[str]


@dataclass(frozen=True)
class Me:
    """The token's user: its accounts with what it may do on each, and
    what it may do beyond one account."""

    accounts: list[MeAccount]
    operations: frozenset[str]


@dataclass(frozen=True)
class Folder:
    id: str
    name: str
    role: str | None
    unread: int | None
    total: int | None


@dataclass(frozen=True)
class Page:
    """A page of message summaries, as the API describes them."""

    items: list[dict[str, Any]]
    next_cursor: str | None
    # Accounts that did not answer, as "account: why".
    not_answering: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Changes:
    """Changes after a point in the change feed, oldest first: type, id,
    account_id and at, ids only."""

    changes: list[dict[str, str]]
    state: str
    more: bool


@dataclass(frozen=True)
class Outcome:
    """A batch: the ids done, and per failed id why not."""

    done: list[str]
    failed: list[dict[str, str]]


@dataclass(frozen=True)
class Sent:
    message_id_header: str | None
    refused: list[str]


class MailboxApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")
        token = token if token is not None else os.environ.get(TOKEN_ENV, "")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=httpx.Timeout(30.0, connect=5.0),
            transport=transport,
        )

    # --- the wire ---------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """The JSON the API answers, None for no content. Parameters and
        fields that are None are left out of the request."""
        response = await self._send(
            method,
            path,
            params=_given(params),
            json=_given(json) if json is not None else None,
            headers=dict(headers or {}),
        )
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:
            raise ApiError(
                response.status_code, "unexpected_response", "the answer is not JSON"
            ) from None

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TransportError:
            raise self._unreachable() from None
        if response.is_error:
            raise _api_error(response)
        return response

    def _unreachable(self) -> ServiceUnavailableError:
        return ServiceUnavailableError(
            f"The mailbox service is not reachable at {self.base_url}. "
            "Start it with `benethos-mailbox-service serve`."
        )

    # --- the caller and the accounts --------------------------------------------------

    async def me(self) -> Me:
        found = await self.request("GET", "/v1/me")
        return Me(
            accounts=[
                MeAccount(
                    id=str(a["id"]),
                    email=str(a["email"]),
                    display_name=a.get("display_name"),
                    operations=frozenset(a.get("operations", [])),
                    warnings=frozenset(a.get("warnings", [])),
                )
                for a in found.get("accounts", [])
            ],
            operations=frozenset(found.get("operations", [])),
        )

    # --- folders ----------------------------------------------------------------------

    async def list_folders(self, account_id: str) -> list[Folder]:
        found = await self.request("GET", _path("accounts", account_id, "folders"))
        return [_folder(item) for item in found]

    async def create_folder(
        self, account_id: str, name: str, parent_id: str | None
    ) -> Folder:
        """A new folder. ``parent_id`` may be a role such as ``archive``."""
        item = await self.request(
            "POST",
            _path("accounts", account_id, "folders"),
            json={"name": name, "parent_id": parent_id},
        )
        return _folder(item)

    # --- messages ---------------------------------------------------------------------

    async def list_messages(
        self,
        account_id: str | None,
        *,
        folder: str | None = None,
        text: str | None = None,
        sender: str | None = None,
        to: str | None = None,
        subject: str | None = None,
        after: str | None = None,
        before: str | None = None,
        unread: bool | None = None,
        starred: bool | None = None,
        has_attachments: bool | None = None,
        limit: int,
        cursor: str | None = None,
    ) -> Page:
        """One account's messages, or with ``account_id`` None, those of
        every account the caller may read. ``folder`` is an id or a role.
        Across accounts it must be a role."""
        path = (
            _path("accounts", account_id, "messages") if account_id else "/v1/messages"
        )
        found = await self.request(
            "GET",
            path,
            params={
                "folder": folder,
                "q": text,
                "from": sender,
                "to": to,
                "subject": subject,
                "after": after,
                "before": before,
                "unread": unread,
                "starred": starred,
                "has_attachments": has_attachments,
                "limit": limit,
                "cursor": cursor,
            },
        )
        return _page(found)

    async def list_changes(
        self, account_id: str | None, *, since: str | None, limit: int
    ) -> Changes:
        """The changes of one account, or with ``account_id`` None, of every
        account the caller may read, after the point ``since``."""
        path = _path("accounts", account_id, "changes") if account_id else "/v1/changes"
        found = await self.request("GET", path, params={"since": since, "limit": limit})
        return Changes(
            changes=[
                {key: str(change[key]) for key in ("type", "id", "account_id", "at")}
                for change in found.get("changes", [])
            ],
            state=str(found["state"]),
            more=bool(found.get("more")),
        )

    async def get_message(self, account_id: str, message_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(
            "GET", _path("accounts", account_id, "messages", message_id)
        )
        return result

    async def get_attachment(
        self, account_id: str, message_id: str, attachment_id: str, max_bytes: int
    ) -> Attachment:
        """The attachment's bytes up to ``max_bytes``, with its type, charset
        and file name. Reading stops where the limit is passed."""
        path = _path(
            "accounts", account_id, "messages", message_id, "attachments", attachment_id
        )
        try:
            async with self._http.stream("GET", path) as response:
                if response.is_error:
                    await response.aread()
                    raise _api_error(response)
                chunks: list[bytes] = []
                read = 0
                complete = True
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    read += len(chunk)
                    if read > max_bytes:
                        complete = False
                        break
        except httpx.TransportError:
            raise self._unreachable() from None
        media, _, options = response.headers.get(
            "content-type", "application/octet-stream"
        ).partition(";")
        charset = re.search(r"charset=\"?([\w.:-]+)", options)
        name = re.search(
            r"filename\*=UTF-8''([^;]+)",
            response.headers.get("content-disposition", ""),
        )
        return Attachment(
            data=b"".join(chunks)[:max_bytes],
            content_type=media.strip().lower(),
            charset=_known_charset(charset.group(1)) if charset else None,
            filename=unquote(name.group(1)) if name else None,
            complete=complete,
        )

    async def update_messages(
        self,
        account_id: str,
        message_ids: list[str],
        *,
        unread: bool | None = None,
        starred: bool | None = None,
        folder_id: str | None = None,
    ) -> Outcome:
        """Flags and a move for many messages at once. ``folder_id`` may be
        a role such as ``archive``."""
        changes: dict[str, Any] = {"unread": unread, "starred": starred}
        if folder_id is not None:
            changes["folder_ids"] = [folder_id]
        return await self._batch(
            account_id,
            {"ids": message_ids, "action": "update", "changes": _given(changes)},
        )

    async def trash_messages(self, account_id: str, message_ids: list[str]) -> Outcome:
        return await self._batch(account_id, {"ids": message_ids, "action": "delete"})

    async def _batch(self, account_id: str, body: dict[str, Any]) -> Outcome:
        found = await self.request(
            "POST", _path("accounts", account_id, "messages", "batch"), json=body
        )
        done, failed = [], []
        for item in found.get("results", []):
            if item.get("ok"):
                done.append(str(item["id"]))
            else:
                error = item.get("error") or {}
                failed.append(
                    {"id": str(item["id"]), "error": error.get("message", "failed")}
                )
        return Outcome(done, failed)

    # --- drafts and sending -----------------------------------------------------------

    async def list_drafts(
        self, account_id: str, limit: int, cursor: str | None
    ) -> Page:
        found = await self.request(
            "GET",
            _path("accounts", account_id, "drafts"),
            params={"limit": limit, "cursor": cursor},
        )
        return _page(found)

    async def create_draft(
        self, account_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        """Takes ``message`` as ``message_body`` makes it. Answers the draft's
        summary."""
        result: dict[str, Any] = await self.request(
            "POST", _path("accounts", account_id, "drafts"), json=message
        )
        return result

    async def update_draft(
        self,
        account_id: str,
        draft_id: str,
        message: dict[str, Any],
        keep_attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        """``keep_attachments``: ids of the stored draft's attachments that
        stay. None or empty: none of them."""
        result: dict[str, Any] = await self.request(
            "PUT",
            _path("accounts", account_id, "drafts", draft_id),
            json={**message, "keep_attachments": keep_attachments or None},
        )
        return result

    async def delete_draft(self, account_id: str, draft_id: str) -> None:
        await self.request("DELETE", _path("accounts", account_id, "drafts", draft_id))

    async def send_message(
        self, account_id: str, message: dict[str, Any], idempotency_key: str
    ) -> Sent:
        found = await self.request(
            "POST",
            _path("accounts", account_id, "send"),
            json=message,
            headers={"Idempotency-Key": idempotency_key},
        )
        return _sent(found)

    async def send_draft(
        self, account_id: str, draft_id: str, idempotency_key: str
    ) -> Sent:
        found = await self.request(
            "POST",
            _path("accounts", account_id, "drafts", draft_id, "send"),
            headers={"Idempotency-Key": idempotency_key},
        )
        return _sent(found)

    async def aclose(self) -> None:
        await self._http.aclose()


def message_body(
    *,
    to: list[Recipient],
    cc: list[Recipient],
    bcc: list[Recipient],
    subject: str,
    text: str,
    html: str | None,
    reference: tuple[str, str] | None,
) -> dict[str, Any]:
    """The body of a draft or a message to send, as the API takes it.
    ``reference``: the id of the message answered or forwarded, and the
    action (reply, reply_all, forward)."""
    body: dict[str, Any] = {
        "to": [_recipient(r) for r in to],
        "cc": [_recipient(r) for r in cc],
        "bcc": [_recipient(r) for r in bcc],
        "subject": subject,
        "text": text,
    }
    if html is not None:
        body["html"] = html
    if reference is not None:
        body["reference"] = {"message_id": reference[0], "action": reference[1]}
    return body


def _recipient(recipient: Recipient) -> dict[str, str]:
    email, name = recipient
    return {"email": email, "name": name} if name else {"email": email}


def _path(*parts: str) -> str:
    """A path below ``/v1``, each part quoted: an id comes from the model."""
    return "/v1/" + "/".join(quote(part, safe="") for part in parts)


def _given(values: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (values or {}).items() if v is not None}


def _folder(item: dict[str, Any]) -> Folder:
    return Folder(
        id=str(item["id"]),
        name=str(item["name"]),
        role=item.get("role"),
        unread=item.get("unread"),
        total=item.get("total"),
    )


def _page(found: dict[str, Any]) -> Page:
    return Page(
        items=list(found.get("items", [])),
        next_cursor=found.get("next_cursor"),
        not_answering=[
            f"{f['account_id']}: {f['message']}" for f in found.get("incomplete") or []
        ],
    )


def _sent(found: dict[str, Any]) -> Sent:
    return Sent(
        message_id_header=found.get("message_id_header"),
        refused=list(found.get("refused") or []),
    )


def _api_error(response: httpx.Response) -> ApiError:
    """The error envelope as an ApiError. A validation failure (422) has no
    envelope but a list of what was wrong where, which is what the model
    needs to correct the call."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        if "code" in error and "message" in error:
            code, message = str(error["code"]), str(error["message"])
            return ApiError(response.status_code, code, message)
    if isinstance(body, dict) and isinstance(body.get("detail"), list):
        reasons = [
            f"{'.'.join(str(p) for p in item.get('loc', ()) if p != 'body')}: "
            f"{item.get('msg', '')}"
            for item in body["detail"]
            if isinstance(item, dict)
        ]
        if reasons:
            reason = "; ".join(reasons)
            return ApiError(response.status_code, "validation_error", reason)
    return ApiError(response.status_code, "unexpected_response", response.reason_phrase)


def _known_charset(name: str) -> str | None:
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name
