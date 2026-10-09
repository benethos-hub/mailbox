"""``SyncMailboxClient``, the client for code without an event loop: it
sends the calls of ``endpoints`` with ``httpx.Client``, the same calls
``MailboxClient`` sends. Each method is one line, what it asks and what
it answers is described in ``endpoints``."""

from __future__ import annotations

from types import TracebackType
from typing import Any, TypeVar

import httpx

from . import endpoints
from .answers import api_error, failure, read
from .attachments import Collected, attachment
from .calls import Call, blocking, timeouts
from .environment import connection
from .models import Attachment

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
        return read(call, response)

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

    # --- the caller -------------------------------------------------------------------

    get_me = blocking(endpoints.get_me)

    # --- folders ----------------------------------------------------------------------

    list_folders = blocking(endpoints.list_folders)
    create_folder = blocking(endpoints.create_folder)
    update_folder = blocking(endpoints.update_folder)
    delete_folder = blocking(endpoints.delete_folder)

    # --- messages ---------------------------------------------------------------------

    list_messages = blocking(endpoints.list_messages)
    list_changes = blocking(endpoints.list_changes)
    get_message = blocking(endpoints.get_message)
    get_message_raw = blocking(endpoints.get_message_raw)
    update_messages = blocking(endpoints.update_messages)
    trash_messages = blocking(endpoints.trash_messages)
    delete_message = blocking(endpoints.delete_message)

    # --- drafts and sending -----------------------------------------------------------

    list_drafts = blocking(endpoints.list_drafts)
    create_draft = blocking(endpoints.create_draft)
    update_draft = blocking(endpoints.update_draft)
    delete_draft = blocking(endpoints.delete_draft)
    send_message = blocking(endpoints.send_message)
    send_draft = blocking(endpoints.send_draft)

    # --- webhooks ---------------------------------------------------------------------

    update_webhook = blocking(endpoints.update_webhook)
    renew_webhook_secret = blocking(endpoints.renew_webhook_secret)

    # --- accounts ---------------------------------------------------------------------

    list_accounts = blocking(endpoints.list_accounts)
    create_account = blocking(endpoints.create_account)
    get_account = blocking(endpoints.get_account)
    update_account = blocking(endpoints.update_account)
    delete_account = blocking(endpoints.delete_account)
    verify_account = blocking(endpoints.verify_account)

    # --- discovery and the sign-in with a code ----------------------------------------

    discover_account = blocking(endpoints.discover_account)
    start_device_oauth = blocking(endpoints.start_device_oauth)
    poll_device_oauth = blocking(endpoints.poll_device_oauth)

    # --- attachments ------------------------------------------------------------------

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
