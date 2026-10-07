"""The IMAP adapter: one account, one connection, one lock.

IMAP connections are stateful (the selected folder), so every operation
runs as one uninterrupted sequence under the account's lock, in a worker
thread (``MailServerAdapter``). The sequences themselves are in
``messages``, ``folders``, ``drafts`` and ``sync``, each on the
``Mailbox`` of one step. IDLE waits over a connection of its own
(``watch``).

Towards the server the adapter is careful (CONCEPT 5.9): ``Guard`` paces
the requests, blocks a rejected login and pauses an unreachable server.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial
from typing import TypeVar

import anyio

from ....common.chunks import batched
from ....common.ratelimit import Clock, Sleep
from ....errors import BadRequestError, MailboxServiceError, NotSupportedError
from ...models import (
    AttachmentContent,
    Folder,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from ...protocols import IMAP_PORTS, Pick, SmtpSession
from .. import rules
from ..base import Capability, CredentialReader, ProviderSettings
from ..guard import Pace
from ..mailserver import MailServerAdapter
from ..sender import SmtpFactory
from . import drafts, folders, messages, sync
from .connect import SessionFactory, default_session
from .mailbox import Mailbox
from .watch import Idle

T = TypeVar("T")

# Message-ID headers fetched per request during a sync.
HEADER_BATCH = 200


class ImapProvider(MailServerAdapter):
    protocol = "IMAP"
    account = "an IMAP account"
    ports = IMAP_PORTS
    # PUSH needs IDLE, which wait_for_change finds out after the login.
    capabilities = frozenset({Capability.SEARCH, Capability.SERVER_SEARCH})

    def __init__(
        self,
        settings: ProviderSettings,
        credentials: CredentialReader,
        session_factory: SessionFactory = default_session,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
        smtp_factory: SmtpFactory = SmtpSession,
        pick: Pick | None = None,
        pace: Pace | None = None,
        watchers: anyio.CapacityLimiter | None = None,
    ) -> None:
        """``pick`` checks the host of each connection, IMAP and SMTP.
        ``pace`` is how fast requests go, unless the settings name a rate.
        ``watchers`` bounds the threads that wait in IDLE, shared by every
        adapter."""
        super().__init__(
            settings,
            credentials,
            clock=clock,
            sleep=sleep,
            jitter=jitter,
            smtp_factory=smtp_factory,
            pick=pick,
            pace=pace,
        )
        self._session = session_factory(self._server)
        self._box = Mailbox(self._session, self.capabilities)
        # IDLE blocks its connection, so it gets one of its own.
        self._idle = Idle(
            session_factory(self._server), self._guard, self._login, watchers
        )

    def _check_auth(self, auth: str) -> None:
        if auth == "xoauth2":
            # Nothing renews the access token yet (CONCEPT 5.1): the login
            # would be rejected within the hour.
            raise NotSupportedError(
                "IMAP with OAuth (settings.auth 'xoauth2') is not supported yet: "
                "the service cannot renew the token. Use a password or an app "
                "password."
            )
        if auth != "password":
            raise BadRequestError("settings.auth must be 'password'")

    # --- Reads ------------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return await self._run(lambda box: box.list_folders(subscriptions=True))

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        return await self._run(
            lambda box: messages.list_messages(box, folder_id, limit, cursor, search)
        )

    async def get_message(self, message_id: str) -> Message:
        return await self._run(lambda box: messages.get_message(box, message_id))

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return await self._run(
            lambda box: messages.get_attachment(box, message_id, attachment_id)
        )

    async def get_raw(self, message_id: str) -> bytes:
        return await self._run(lambda box: messages.get_raw(box, message_id))

    async def folder_states(self) -> dict[str, str]:
        return await self._run(sync.folder_states)

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await self._run(lambda box: sync.folder_contents(box, folder_id))

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        return await self._run(
            lambda box: sync.flag_changes(box, folder_id, since, message_ids)
        )

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        # Ids that are no id of this adapter are left out, like messages
        # that are gone.
        found: dict[str, str | None] = {}
        for (folder, validity), by_uid in messages.by_folder(message_ids)[0].items():
            # One request per batch, so a long first sync never holds the
            # connection for long.
            for batch in batched(list(by_uid), HEADER_BATCH):
                headers = partial(
                    sync.message_headers, folder=folder, validity=validity, uids=batch
                )
                found.update(await self._run(headers))
        return found

    async def verify(self) -> None:
        await self._in_thread(
            lambda: self._verified(self._session, lambda: self._login(self._session))
        )

    async def close(self) -> None:
        self._idle.closing()
        await self._in_thread(self._close)

    # --- Sends ------------------------------------------------------------------------

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        refused = await self._send_smtp(raw, sender, recipients)
        # Sent: from here on nothing may fail, or a client would send again.
        try:
            copy = await self._run(lambda box: messages.store_sent(box, raw))
        except MailboxServiceError as exc:
            return SentMessage(refused=refused, copy_error=exc.message)
        return SentMessage(refused=refused, sent_copy=copy)

    # --- Drafts -----------------------------------------------------------------------

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await self._run(lambda box: drafts.list_drafts(box, limit, cursor))

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        return await self._run(
            self._counting(
                lambda box, retried: drafts.save_draft(
                    box, raw, replaces, retried=retried
                )
            )
        )

    async def get_draft(self, draft_id: str) -> bytes:
        return await self._run(lambda box: drafts.get_draft(box, draft_id))

    async def delete_draft(self, draft_id: str) -> None:
        await self._run(lambda box: drafts.delete_draft(box, draft_id))

    # --- Writes -----------------------------------------------------------------------

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return await self._run(
            self._counting(
                lambda box, retried: folders.create_folder(
                    box, name, parent_id, retried
                )
            )
        )

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await self._run(
            self._counting(
                lambda box, retried: folders.update_folder(
                    box, folder_id, name, parent_id, retried
                )
            )
        )

    async def delete_folder(self, folder_id: str) -> None:
        await self._run(
            self._counting(
                lambda box, retried: folders.delete_folder(box, folder_id, retried)
            )
        )

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await self._per_folder(
            message_ids,
            lambda box, folder, validity, uids, _: messages.update_in_folder(
                box, folder, validity, uids, changes
            ),
        )

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await self._per_folder(
            message_ids,
            lambda box, folder, validity, uids, retried: messages.delete_in_folder(
                box, folder, validity, uids, permanent, retried
            ),
        )

    # --- Watches ----------------------------------------------------------------------

    async def wait_for_change(self, timeout: float) -> bool:
        return await self._idle.wait(timeout)

    # --- plumbing ---------------------------------------------------------------------

    async def _per_folder(
        self,
        message_ids: list[str],
        work: Callable[
            [Mailbox, str, int, list[int], bool], dict[int, T | MailboxServiceError]
        ],
    ) -> dict[str, T | MailboxServiceError]:
        """Run ``work`` once per folder, each under the lock. A failure of
        the connection or the login stops everything. Any other failure
        answers for that folder's messages only."""
        found, unknown = messages.by_folder(message_ids)
        results: dict[str, T | MailboxServiceError] = dict(unknown)
        for (folder, validity), by_uid in found.items():
            step = _in_folder(work, folder, validity, list(by_uid))
            try:
                done = await self._run(self._counting(step))
            except rules.FATAL:
                raise
            except MailboxServiceError as exc:
                done = dict.fromkeys(by_uid, exc)
            for uid, outcome in done.items():
                results[by_uid[uid]] = outcome
        return results

    async def _run(self, operation: Callable[[Mailbox], T]) -> T:
        """One step under the lock, logged in first, through the guard."""
        return await self._in_thread(
            lambda: self._attempted(self._session, partial(self._step, operation))
        )

    def _step(self, operation: Callable[[Mailbox], T]) -> T:
        self._box.fresh()
        if not self._session.connected:
            self._login(self._session)
        return operation(self._box)

    def _close(self) -> None:
        self._closed(self._session)
        self._idle.close()


def _in_folder(
    work: Callable[[Mailbox, str, int, list[int], bool], T],
    folder: str,
    validity: int,
    uids: list[int],
) -> Callable[[Mailbox, bool], T]:
    """``work`` for one folder's messages, to be retried."""
    return lambda box, retried: work(box, folder, validity, uids, retried)
