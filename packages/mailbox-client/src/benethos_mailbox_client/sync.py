"""``SyncMailboxClient``, the client for code without an event loop: it
sends the calls of ``endpoints`` with ``httpx.Client``, the same calls
``MailboxClient`` sends. Each method is one line, what it asks and what
it answers is described in ``endpoints``."""

from __future__ import annotations

from types import TracebackType
from typing import Any, TypeVar

import httpx

from . import endpoints
from .models import Attachment, Changes, Folder, Me, Outcome, Page, Sent
from .wire import (
    Call,
    Collected,
    answer,
    api_error,
    attachment,
    connection,
    failure,
    timeouts,
)

T = TypeVar("T")


class SyncMailboxClient:
    """The REST API of mailbox-service, for code without an event loop. It
    takes the same arguments as ``MailboxClient`` and answers the same.

    ``base_url`` defaults to ``MAILBOX_SERVICE_URL``, ``token`` to
    ``MAILBOX_SERVICE_TOKEN``. Raises ``ConfigurationError`` without a
    token, and for http to another machine unless ``allow_http`` (else
    ``MAILBOX_SERVICE_ALLOW_HTTP``) allows it. ``transport`` is for tests,
    e.g. ``httpx.MockTransport``."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        allow_http: bool | None = None,
    ) -> None:
        found = connection(base_url, token, allow_http)
        self.base_url = found.base_url
        self._http = httpx.Client(
            base_url=found.base_url,
            headers=found.headers,
            timeout=timeouts(),
            transport=transport,
        )

    def __enter__(self) -> SyncMailboxClient:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def send(self, call: Call[T]) -> T:
        """Send ``call`` and read its answer."""
        try:
            response = self._http.request(
                call.method,
                call.path,
                params=call.params,
                json=call.json,
                headers=call.headers,
                timeout=call.timeouts,
            )
        except httpx.TransportError as exc:
            raise failure(exc, self.base_url, call.timeout) from None
        return call.read(answer(response))

    def request(
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
        return self.send(call)

    # --- the caller and the accounts --------------------------------------------------

    def me(self) -> Me:
        return self.send(endpoints.me())

    # --- folders ----------------------------------------------------------------------

    def list_folders(self, account_id: str) -> list[Folder]:
        return self.send(endpoints.list_folders(account_id))

    def create_folder(
        self, account_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return self.send(endpoints.create_folder(account_id, name, parent_id))

    # --- messages ---------------------------------------------------------------------

    def list_messages(
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
        return self.send(
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

    def list_changes(
        self, account_id: str | None, *, since: str | None, limit: int
    ) -> Changes:
        return self.send(endpoints.list_changes(account_id, since=since, limit=limit))

    def get_message(self, account_id: str, message_id: str) -> dict[str, Any]:
        return self.send(endpoints.get_message(account_id, message_id))

    def get_attachment(
        self, account_id: str, message_id: str, attachment_id: str, max_bytes: int
    ) -> Attachment:
        """The attachment's bytes up to ``max_bytes``, with its type, charset
        and file name. Reading stops where the limit is passed."""
        call = endpoints.get_attachment(account_id, message_id, attachment_id)
        collected = Collected(max_bytes)
        try:
            with self._http.stream(
                call.method, call.path, timeout=call.timeouts
            ) as response:
                if response.is_error:
                    response.read()
                    raise api_error(response)
                for chunk in response.iter_bytes():
                    if not collected.add(chunk):
                        break
        except httpx.TransportError as exc:
            raise failure(exc, self.base_url, call.timeout) from None
        return attachment(response.headers, collected)

    def update_messages(
        self,
        account_id: str,
        message_ids: list[str],
        *,
        unread: bool | None = None,
        starred: bool | None = None,
        folder_id: str | None = None,
    ) -> Outcome:
        return self.send(
            endpoints.update_messages(
                account_id,
                message_ids,
                unread=unread,
                starred=starred,
                folder_id=folder_id,
            )
        )

    def trash_messages(self, account_id: str, message_ids: list[str]) -> Outcome:
        return self.send(endpoints.trash_messages(account_id, message_ids))

    # --- drafts and sending -----------------------------------------------------------

    def list_drafts(
        self, account_id: str, limit: int, cursor: str | None = None
    ) -> Page:
        return self.send(endpoints.list_drafts(account_id, limit, cursor))

    def create_draft(self, account_id: str, message: dict[str, Any]) -> dict[str, Any]:
        return self.send(endpoints.create_draft(account_id, message))

    def update_draft(
        self,
        account_id: str,
        draft_id: str,
        message: dict[str, Any],
        keep_attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.send(
            endpoints.update_draft(account_id, draft_id, message, keep_attachments)
        )

    def delete_draft(self, account_id: str, draft_id: str) -> None:
        self.send(endpoints.delete_draft(account_id, draft_id))

    def send_message(
        self, account_id: str, message: dict[str, Any], idempotency_key: str
    ) -> Sent:
        return self.send(endpoints.send_message(account_id, message, idempotency_key))

    def send_draft(self, account_id: str, draft_id: str, idempotency_key: str) -> Sent:
        return self.send(endpoints.send_draft(account_id, draft_id, idempotency_key))
