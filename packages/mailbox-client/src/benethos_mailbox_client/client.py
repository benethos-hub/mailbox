"""``MailboxClient``, the client for async code: it sends the calls of
``endpoints`` with ``httpx.AsyncClient``. Each method is one line, what
it asks and what it answers is described in ``endpoints``."""

from __future__ import annotations

from types import TracebackType
from typing import Any, TypeVar

import httpx

from . import endpoints
from .answers import api_error, failure, read
from .attachments import Collected, attachment
from .calls import Call, awaiting, timeouts
from .environment import connection
from .models import Attachment

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

    # --- the caller -------------------------------------------------------------------

    get_me = awaiting(endpoints.get_me)

    # --- folders ----------------------------------------------------------------------

    list_folders = awaiting(endpoints.list_folders)
    create_folder = awaiting(endpoints.create_folder)
    update_folder = awaiting(endpoints.update_folder)
    delete_folder = awaiting(endpoints.delete_folder)

    # --- messages ---------------------------------------------------------------------

    list_messages = awaiting(endpoints.list_messages)
    list_all_messages = awaiting(endpoints.list_all_messages)
    list_changes = awaiting(endpoints.list_changes)
    list_all_changes = awaiting(endpoints.list_all_changes)
    get_message = awaiting(endpoints.get_message)
    get_message_raw = awaiting(endpoints.get_message_raw)
    update_message = awaiting(endpoints.update_message)
    batch_messages = awaiting(endpoints.batch_messages)
    update_messages = awaiting(endpoints.update_messages)
    trash_messages = awaiting(endpoints.trash_messages)
    delete_message = awaiting(endpoints.delete_message)

    # --- drafts and sending -----------------------------------------------------------

    list_drafts = awaiting(endpoints.list_drafts)
    create_draft = awaiting(endpoints.create_draft)
    update_draft = awaiting(endpoints.update_draft)
    delete_draft = awaiting(endpoints.delete_draft)
    send_message = awaiting(endpoints.send_message)
    send_draft = awaiting(endpoints.send_draft)

    # --- webhooks ---------------------------------------------------------------------

    update_webhook = awaiting(endpoints.update_webhook)
    renew_webhook_secret = awaiting(endpoints.renew_webhook_secret)

    # --- accounts ---------------------------------------------------------------------

    list_accounts = awaiting(endpoints.list_accounts)
    create_account = awaiting(endpoints.create_account)
    get_account = awaiting(endpoints.get_account)
    update_account = awaiting(endpoints.update_account)
    delete_account = awaiting(endpoints.delete_account)
    verify_account = awaiting(endpoints.verify_account)

    # --- discovery and the sign-in with a code ----------------------------------------

    discover_account = awaiting(endpoints.discover_account)
    start_device_oauth = awaiting(endpoints.start_device_oauth)
    poll_device_oauth = awaiting(endpoints.poll_device_oauth)

    # --- users ------------------------------------------------------------------------

    list_users = awaiting(endpoints.list_users)
    create_user = awaiting(endpoints.create_user)
    get_user = awaiting(endpoints.get_user)
    update_user = awaiting(endpoints.update_user)
    delete_user = awaiting(endpoints.delete_user)
    set_password = awaiting(endpoints.set_password)

    # --- attachments ------------------------------------------------------------------

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
