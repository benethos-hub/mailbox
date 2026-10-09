"""``MailboxClient``, the client for async code: it sends the calls of
``endpoints`` with ``httpx.AsyncClient``. Each method is one line, what
it asks and what it answers is described in ``endpoints``."""

from __future__ import annotations

from types import EllipsisType, TracebackType
from typing import Any, TypeVar

import httpx

from . import endpoints
from .answers import api_error, failure, read
from .attachments import Collected, attachment
from .calls import Call, timeouts
from .environment import connection
from .models import (
    Attachment,
    Changes,
    Folder,
    Me,
    Outcome,
    Page,
    Sent,
    Webhook,
    WebhookSecret,
)

T = TypeVar("T")


class MailboxClient:
    """The REST API of mailbox-service, for async code.

    ``base_url`` defaults to ``MAILBOX_SERVICE_URL``, ``token`` to
    ``MAILBOX_SERVICE_TOKEN``. Raises ``ConfigurationError`` without a
    token, and for http to another machine unless ``allow_http`` (else
    ``MAILBOX_SERVICE_ALLOW_HTTP``) allows it. ``transport`` is for tests,
    e.g. ``httpx.MockTransport``."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_http: bool | None = None,
    ) -> None:
        found = connection(base_url, token, allow_http)
        self.base_url = found.base_url
        self._http = httpx.AsyncClient(
            base_url=found.base_url,
            headers=found.headers,
            timeout=timeouts(),
            transport=transport,
        )

    async def __aenter__(self) -> MailboxClient:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def send(self, call: Call[T]) -> T:
        """Send ``call`` and read its answer."""
        try:
            response = await self._http.request(
                call.method,
                call.path,
                params=call.params,
                json=call.json,
                headers=call.headers,
                timeout=call.timeouts,
            )
        except httpx.TransportError as exc:
            raise failure(exc, self.base_url, call.timeout) from None
        return read(call, response)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Any request: the JSON the API answers, None for no content.
        Parameters and fields that are None are left out."""
        call = endpoints.request(
            method, path, params=params, json=json, headers=headers
        )
        return await self.send(call)

    # --- the caller and the accounts --------------------------------------------------

    async def me(self) -> Me:
        return await self.send(endpoints.me())

    # --- folders ----------------------------------------------------------------------

    async def list_folders(self, account_id: str) -> list[Folder]:
        return await self.send(endpoints.list_folders(account_id))

    async def create_folder(
        self, account_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await self.send(endpoints.create_folder(account_id, name, parent_id))

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
        return await self.send(
            endpoints.list_messages(
                account_id,
                folder=folder,
                text=text,
                sender=sender,
                to=to,
                subject=subject,
                after=after,
                before=before,
                unread=unread,
                starred=starred,
                has_attachments=has_attachments,
                limit=limit,
                cursor=cursor,
            )
        )

    async def list_changes(
        self, account_id: str | None, *, since: str | None, limit: int
    ) -> Changes:
        return await self.send(
            endpoints.list_changes(account_id, since=since, limit=limit)
        )

    async def get_message(self, account_id: str, message_id: str) -> dict[str, Any]:
        return await self.send(endpoints.get_message(account_id, message_id))

    async def get_attachment(
        self, account_id: str, message_id: str, attachment_id: str, max_bytes: int
    ) -> Attachment:
        """The attachment's bytes up to ``max_bytes``, with its type, charset
        and file name. Reading stops where the limit is passed."""
        call = endpoints.get_attachment(account_id, message_id, attachment_id)
        collected = Collected(max_bytes)
        try:
            async with self._http.stream(
                call.method, call.path, timeout=call.timeouts
            ) as response:
                if response.is_error:
                    await response.aread()
                    raise api_error(response)
                async for chunk in response.aiter_bytes():
                    if not collected.add(chunk):
                        break
        except httpx.TransportError as exc:
            raise failure(exc, self.base_url, call.timeout) from None
        return attachment(response.headers, collected)

    async def update_messages(
        self,
        account_id: str,
        message_ids: list[str],
        *,
        unread: bool | None = None,
        starred: bool | None = None,
        folder_id: str | None = None,
    ) -> Outcome:
        return await self.send(
            endpoints.update_messages(
                account_id,
                message_ids,
                unread=unread,
                starred=starred,
                folder_id=folder_id,
            )
        )

    async def delete_message(
        self, account_id: str, message_id: str, *, permanent: bool = False
    ) -> None:
        await self.send(
            endpoints.delete_message(account_id, message_id, permanent=permanent)
        )

    async def trash_messages(self, account_id: str, message_ids: list[str]) -> Outcome:
        return await self.send(endpoints.trash_messages(account_id, message_ids))

    # --- drafts and sending -----------------------------------------------------------

    async def list_drafts(
        self, account_id: str, limit: int, cursor: str | None = None
    ) -> Page:
        return await self.send(endpoints.list_drafts(account_id, limit, cursor))

    async def create_draft(
        self, account_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.send(endpoints.create_draft(account_id, message))

    async def update_draft(
        self,
        account_id: str,
        draft_id: str,
        message: dict[str, Any],
        keep_attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self.send(
            endpoints.update_draft(account_id, draft_id, message, keep_attachments)
        )

    async def delete_draft(self, account_id: str, draft_id: str) -> None:
        await self.send(endpoints.delete_draft(account_id, draft_id))

    async def send_message(
        self, account_id: str, message: dict[str, Any], idempotency_key: str
    ) -> Sent:
        return await self.send(
            endpoints.send_message(account_id, message, idempotency_key)
        )

    async def send_draft(
        self, account_id: str, draft_id: str, idempotency_key: str
    ) -> Sent:
        return await self.send(
            endpoints.send_draft(account_id, draft_id, idempotency_key)
        )

    # --- webhooks ---------------------------------------------------------------------

    async def update_webhook(
        self,
        webhook_id: str,
        *,
        url: str | None = None,
        events: list[str] | None = None,
        accounts: list[str] | None | EllipsisType = ...,
    ) -> Webhook:
        return await self.send(
            endpoints.update_webhook(
                webhook_id, url=url, events=events, accounts=accounts
            )
        )

    async def renew_webhook_secret(self, webhook_id: str) -> WebhookSecret:
        return await self.send(endpoints.renew_webhook_secret(webhook_id))
