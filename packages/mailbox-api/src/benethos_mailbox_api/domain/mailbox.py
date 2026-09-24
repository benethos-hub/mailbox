"""Folders and messages: of one account, and across accounts."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from ..data.mail import compose
from ..data.models import (
    AccountFailure,
    AttachmentContent,
    BatchItemResult,
    BatchResult,
    DraftMessage,
    Folder,
    FolderCreate,
    FolderRole,
    FolderUpdate,
    ItemError,
    Message,
    MessageBatch,
    MessagePage,
    MessageReference,
    MessageSummary,
    MessageUpdate,
    OutgoingMessage,
    Page,
    Recipient,
    SendResult,
    SentMessage,
)
from ..data.providers import MailProvider
from ..errors import ConflictError, MailboxApiError, NotFoundError
from . import merge, replies
from .access import Access
from .accounts import AccountService
from .idempotency import Idempotency
from .sync import SyncService

T = TypeVar("T")
S = TypeVar("S", bound=MessageSummary)
M = TypeVar("M", bound=DraftMessage)

log = logging.getLogger(__name__)


class MailboxService:
    """Callers see our stable message ids (``sync``), providers their own."""

    def __init__(
        self, accounts: AccountService, sync: SyncService, idempotency: Idempotency
    ) -> None:
        self._accounts = accounts
        self._sync = sync
        self._idempotency = idempotency

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        access.require("list_folders", account_id)
        return await self._call(account_id, lambda p: p.list_folders())

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        access.require("create_folder", account_id)
        return await self._call(
            account_id, lambda p: p.create_folder(new.name, new.parent_id)
        )

    async def update_folder(
        self, access: Access, account_id: str, folder_id: str, changes: FolderUpdate
    ) -> Folder:
        """Rename or move. Folders with a role stay where mail clients expect
        them. The messages inside keep their ids: a sync follows them."""
        access.require("update_folder", account_id)
        folder = await self._own_folder(account_id, folder_id)
        name = changes.name or folder.name
        parent = changes.parent_id if changes.moves else folder.parent_id
        updated = await self._call(
            account_id, lambda p: p.update_folder(folder_id, name, parent)
        )
        if updated.id != folder_id:
            try:
                await self._sync.sync_account(account_id)
            except MailboxApiError:
                pass  # the next sync, or the next lookup, follows them
        return updated

    async def delete_folder(
        self, access: Access, account_id: str, folder_id: str
    ) -> None:
        """Only an empty folder without subfolders: deleting a folder takes
        its messages with it on many servers, and they cannot be taken back."""
        access.require("delete_folder", account_id)
        folder = await self._own_folder(account_id, folder_id)
        folders = await self._call(account_id, lambda p: p.list_folders())
        if any(f.parent_id == folder_id for f in folders):
            raise ConflictError(f"the folder {folder.name} has subfolders")
        contents = await self._call(account_id, lambda p: p.folder_contents(folder_id))
        if contents:
            raise ConflictError(
                f"the folder {folder.name} holds {len(contents)} messages: "
                "move or delete them first"
            )
        await self._call(account_id, lambda p: p.delete_folder(folder_id))

    async def _own_folder(self, account_id: str, folder_id: str) -> Folder:
        """A folder the user made: one with a role is refused."""
        folders = await self._call(account_id, lambda p: p.list_folders())
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            raise NotFoundError(f"folder {folder_id} not found")
        if folder.role is not None:
            raise ConflictError(
                f"the folder {folder.name} is the account's {folder.role}: "
                "it stays as it is"
            )
        return folder

    async def list_messages(
        self,
        access: Access,
        account_id: str,
        *,
        folder_id: str | None,
        query: str | None,
        unread: bool | None,
        limit: int,
        cursor: str | None,
    ) -> Page[MessageSummary]:
        access.require("list_messages", account_id)
        page = await self._call(
            account_id,
            lambda p: p.list_messages(
                folder_id, limit=limit, cursor=cursor, query=query, unread=unread
            ),
        )
        return Page[MessageSummary](
            items=await self._published(account_id, page.items),
            next_cursor=page.next_cursor,
        )

    async def list_all_messages(
        self,
        access: Access,
        *,
        account_ids: list[str] | None,
        folder_role: FolderRole | None,
        query: str | None,
        unread: bool | None,
        limit: int,
        cursor: str | None,
    ) -> MessagePage:
        """Messages of several accounts, merged newest first.

        Accounts the caller may not read are left out without a word, like in
        ``list_accounts``. An account that fails leaves the page incomplete,
        it does not fail the request.
        """
        existing = set(self._accounts.all_ids())
        wanted = account_ids or self._accounts.all_ids()
        visible = [
            a
            for a in dict.fromkeys(wanted)
            if a in existing and access.allows("list_all_messages", a)
        ]
        failures: list[AccountFailure] = []
        if cursor:
            positions = {
                a: p for a, p in merge.decode_cursor(cursor).items() if a in visible
            }
        else:
            positions = await self._start(visible, folder_role, failures)

        chunks = await merge.per_account(
            [a for a, p in positions.items() if not p.done],
            lambda a: self._window(a, positions[a], query, unread, limit),
            failures,
        )

        merged = [
            (item, account_id)
            for account_id, window in chunks.items()
            for chunk in window
            for item in chunk.items
        ]
        merged.sort(key=lambda pair: merge.newest_first(pair[0]))
        taken = merged[:limit]
        published: dict[str, list[MessageSummary]] = {}
        for account_id, window in chunks.items():
            mine = [item for item, owner in taken if owner == account_id]
            positions[account_id] = merge.advance(
                positions[account_id], window, len(mine)
            )
            # Only what is handed out gets our ids.
            published[account_id] = await self._published(account_id, mine)

        more = any(not p.done for p in positions.values())
        return MessagePage(
            items=[published[owner].pop(0) for _, owner in taken],
            next_cursor=merge.encode_cursor(positions) if more else None,
            incomplete=failures,
        )

    async def get_message(
        self, access: Access, account_id: str, message_id: str
    ) -> Message:
        access.require("get_message", account_id)
        message = await self._on_message(
            account_id, message_id, lambda p, native: p.get_message(native)
        )
        return _public(message, message_id, account_id)

    async def update_message(
        self,
        access: Access,
        account_id: str,
        message_id: str,
        changes: MessageUpdate,
    ) -> MessageSummary:
        access.require("update_message", account_id)
        outcome = (await self._update(account_id, [message_id], changes))[message_id]
        if isinstance(outcome, MailboxApiError):
            raise outcome
        return outcome

    async def delete_message(
        self, access: Access, account_id: str, message_id: str, permanent: bool
    ) -> None:
        """Into the trash, or for good: then its own right (CONCEPT 7.5)."""
        access.require(_delete_right(permanent), account_id)
        outcome = (await self._delete(account_id, [message_id], permanent))[message_id]
        if isinstance(outcome, MailboxApiError):
            raise outcome

    async def send_message(
        self,
        access: Access,
        account_id: str,
        message: OutgoingMessage,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Send from the account's address, with a fresh Date and
        Message-ID. Its own right: sending cannot be taken back. With an
        ``idempotency_key`` a retry returns the first result."""
        access.require("send_message", account_id)
        if message.reference is not None:
            # A reply quotes the original and a forward passes it on: whoever
            # may only send must not get at mail this way.
            access.require("get_message", account_id)
        return await self._idempotency.run(
            account_id,
            idempotency_key,
            "send_message",
            message,
            lambda: self._send(account_id, message),
            SendResult,
        )

    async def _send(self, account_id: str, message: OutgoingMessage) -> SendResult:
        account = self._accounts.record(account_id)
        raw, message_id, message, original = await self._compose(
            account_id, message, draft=False
        )
        sent = await self._call(
            account_id,
            lambda p: p.send(raw, account.email, message.recipients()),
        )
        if message.reference is not None and original is not None:
            await self._mark_answered(account_id, message.reference, original)
        return await self._send_result(account_id, message_id, sent)

    async def _send_result(
        self, account_id: str, message_id: str, sent: SentMessage
    ) -> SendResult:
        copy_id = None
        if sent.sent_copy is not None:
            copy = sent.sent_copy
            [copy_id] = await self._sync.public_ids(
                account_id, [(copy.id, _folder_of(copy))]
            )
        return SendResult(
            message_id_header=message_id, sent_copy_id=copy_id, refused=sent.refused
        )

    async def _compose(
        self, account_id: str, message: M, *, draft: bool
    ) -> tuple[bytes, str, M, Message | None]:
        """The message as bytes, from the account's address, with a fresh
        Date and Message-ID. A reference is filled in from the original.
        Returns the bytes, the Message-ID, the message as filled in and the
        original, if any."""
        account = self._accounts.record(account_id)
        extras = compose.Extras()
        original: Message | None = None
        reference = message.reference
        if reference is not None:
            original = await self._on_message(
                account_id,
                reference.message_id,
                lambda p, native: p.get_message(native),
            )
            message, extras = await self._answer(
                account_id, account.email, message, reference, original
            )
        message_id = compose.new_message_id(account.email)
        raw = compose.message(
            message,
            Recipient(email=account.email, name=account.display_name),
            # Local time with its offset, as mail clients write it.
            datetime.now(UTC).astimezone(),
            message_id,
            extras,
            draft=draft,
            reference=_reference_header(reference) if reference else None,
        )
        return raw, message_id, message, original

    async def _answer(
        self,
        account_id: str,
        own_address: str,
        message: M,
        reference: MessageReference,
        original: Message,
    ) -> tuple[M, compose.Extras]:
        """Fetch what the reply or forward needs of the original; ``replies``
        makes it."""
        raw = await self._on_message(
            account_id, reference.message_id, lambda p, native: p.get_raw(native)
        )
        if reference.action != "forward":
            return replies.reply(message, reference.action, original, raw, own_address)
        files: list[replies.AttachedFile] = []
        if reference.forward_as == "inline":
            for attachment in original.attachments:
                content = await self._attachment(
                    account_id, reference.message_id, attachment.id
                )
                files.append(
                    (
                        attachment.filename or attachment.id,
                        attachment.content_type,
                        content.data,
                    )
                )
        return replies.forward(message, reference.forward_as, original, raw, files)

    async def _attachment(
        self, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return await self._on_message(
            account_id,
            message_id,
            lambda p, native: p.get_attachment(native, attachment_id),
        )

    async def _mark_answered(
        self, account_id: str, reference: MessageReference, original: Message
    ) -> None:
        """``$answered`` or ``$forwarded`` on the original, so other clients
        show it too. The message is sent already: a failure here is logged."""
        keyword = replies.answered_keyword(reference)
        changes = MessageUpdate(keywords=sorted({*original.keywords, keyword}))
        try:
            outcome = await self._update(account_id, [reference.message_id], changes)
            failure = outcome[reference.message_id]
            if isinstance(failure, MailboxApiError):
                raise failure
        except MailboxApiError as exc:
            log.warning(
                "sent, but %s not set on the original: %s", keyword, exc.message
            )

    # --- drafts ---------------------------------------------------------------------

    async def list_drafts(
        self, access: Access, account_id: str, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        access.require("list_drafts", account_id)
        page = await self._call(
            account_id, lambda p: p.list_drafts(limit=limit, cursor=cursor)
        )
        return Page[MessageSummary](
            items=await self._published(account_id, page.items),
            next_cursor=page.next_cursor,
        )

    async def create_draft(
        self, access: Access, account_id: str, draft: DraftMessage
    ) -> MessageSummary:
        """Store a draft in the drafts folder, composed like a message to
        send. A reference is filled in now and remembered for the send."""
        _require_draft_right(access, "create_draft", account_id, draft)
        raw, _, _, _ = await self._compose(account_id, draft, draft=True)
        saved = await self._call(account_id, lambda p: p.save_draft(raw, None))
        [published] = await self._published(account_id, [saved])
        return published

    async def update_draft(
        self, access: Access, account_id: str, draft_id: str, draft: DraftMessage
    ) -> MessageSummary:
        """Replace a draft. It keeps its id, though the provider stores a
        new message and removes the old one."""
        _require_draft_right(access, "update_draft", account_id, draft)
        raw, _, _, _ = await self._compose(account_id, draft, draft=True)
        saved = await self._on_message(
            account_id, draft_id, lambda p, native: p.save_draft(raw, native)
        )
        self._sync.relocate(account_id, draft_id, saved.id, _folder_of(saved))
        [public] = await self._sync.public_ids(
            account_id, [(saved.id, _folder_of(saved))]
        )
        return _public(saved, public, account_id)

    async def delete_draft(
        self, access: Access, account_id: str, draft_id: str
    ) -> None:
        """For good: a draft is not kept in the trash."""
        access.require("delete_draft", account_id)
        await self._on_message(
            account_id, draft_id, lambda p, native: p.delete_draft(native)
        )
        self._sync.forget(account_id, draft_id)

    async def batch_messages(
        self, access: Access, account_id: str, batch: MessageBatch
    ) -> BatchResult:
        """One action for many messages. The rights are those of the single
        operation, checked once for the whole batch."""
        access.require("batch_messages", account_id)
        outcomes: dict[str, Any]
        if batch.action == "update":
            access.require("update_message", account_id)
            assert batch.changes is not None
            outcomes = await self._update(account_id, batch.ids, batch.changes)
        else:
            access.require(_delete_right(batch.permanent), account_id)
            outcomes = await self._delete(account_id, batch.ids, batch.permanent)
        return BatchResult(results=[_item(i, outcomes[i]) for i in batch.ids])

    # --- changing, one or many ------------------------------------------------------

    async def _update(
        self, account_id: str, ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxApiError]:
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: p.update_messages(n, changes)
        )
        results: dict[str, MessageSummary | MailboxApiError] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxApiError):
                results[message_id] = outcome
                continue
            self._follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = _public(outcome, message_id, account_id)
        return results

    async def _delete(
        self, account_id: str, ids: list[str], permanent: bool
    ) -> dict[str, None | MailboxApiError]:
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: p.delete_messages(n, permanent)
        )
        results: dict[str, None | MailboxApiError] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxApiError):
                results[message_id] = outcome
                continue
            if permanent:
                self._sync.forget(account_id, message_id)
            elif outcome is not None:
                self._follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = None
        return results

    async def _on_messages(
        self,
        account_id: str,
        ids: list[str],
        run: Callable[[MailProvider, list[str]], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Run a provider operation on the messages behind ``ids``. Those
        the provider does not find where the index says get one sync and a
        second try. Returns the outcome per id and the provider id used."""
        natives = {i: n for i, n in self._sync.natives(account_id, ids).items() if n}
        outcomes: dict[str, Any] = {
            i: NotFoundError(f"message {i} not found") for i in ids if i not in natives
        }
        outcomes.update(await self._run_on(account_id, natives, run))
        missing = [i for i in natives if isinstance(outcomes[i], NotFoundError)]
        if missing and self._sync.mapped(account_id):
            await self._sync.sync_account(account_id)
            moved = {
                i: n
                for i, n in self._sync.natives(account_id, missing).items()
                if n and n != natives[i]
            }
            outcomes.update(await self._run_on(account_id, moved, run))
            natives.update(moved)
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, NotFoundError):
                outcomes[message_id] = NotFoundError(f"message {message_id} not found")
        return outcomes, natives

    async def _run_on(
        self,
        account_id: str,
        natives: dict[str, str],
        run: Callable[[MailProvider, list[str]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not natives:
            return {}
        by_native = await self._call(
            account_id, lambda p: run(p, list(natives.values()))
        )
        missing = NotFoundError("message not found")
        return {i: by_native.get(n, missing) for i, n in natives.items()}

    def _follow(
        self, account_id: str, message_id: str, native: str, now: MessageSummary
    ) -> None:
        """A message the provider moved: its id points to the new place."""
        if now.id != native:
            self._sync.relocate(account_id, message_id, now.id, _folder_of(now))

    async def get_raw(self, access: Access, account_id: str, message_id: str) -> bytes:
        access.require("get_message_raw", account_id)
        return await self._on_message(
            account_id, message_id, lambda p, native: p.get_raw(native)
        )

    async def get_attachment(
        self, access: Access, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        access.require("get_attachment", account_id)
        return await self._attachment(account_id, message_id, attachment_id)

    # --- ids -------------------------------------------------------------------------

    async def _published(
        self, account_id: str, items: list[MessageSummary]
    ) -> list[MessageSummary]:
        """The provider's summaries with our ids and the account."""
        ids = await self._sync.public_ids(
            account_id, [(i.id, _folder_of(i)) for i in items]
        )
        return [
            _public(item, public, account_id)
            for item, public in zip(items, ids, strict=True)
        ]

    async def _on_message(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[MailProvider, str], Awaitable[T]],
    ) -> T:
        return await self._sync.resolve(
            account_id,
            message_id,
            lambda native: self._call(account_id, lambda p: operation(p, native)),
        )

    # --- across accounts ---------------------------------------------------------

    async def _start(
        self,
        account_ids: list[str],
        role: FolderRole | None,
        failures: list[AccountFailure],
    ) -> dict[str, merge.Position]:
        if role is None:
            return {a: merge.Position(None, None, 0) for a in account_ids}
        folders = await merge.per_account(
            account_ids, lambda a: self._call(a, lambda p: p.list_folders()), failures
        )
        positions = {}
        for account_id, found in folders.items():
            match = next((f for f in found if f.role is role), None)
            if match is not None:
                positions[account_id] = merge.Position(match.id, None, 0)
        return positions

    async def _window(
        self,
        account_id: str,
        position: merge.Position,
        query: str | None,
        unread: bool | None,
        limit: int,
    ) -> list[merge.Chunk]:
        """At least ``limit`` of the account's next messages, or all it has
        left, so that merging by date cannot skip a newer one."""

        async def page(cursor: str | None) -> Page[MessageSummary]:
            return await self._call(
                account_id,
                lambda p: p.list_messages(
                    position.folder_id,
                    limit=limit,
                    cursor=cursor,
                    query=query,
                    unread=unread,
                ),
            )

        first = await page(position.cursor)
        chunks = [
            merge.Chunk(
                position.cursor,
                position.offset,
                first.items[position.offset :],
                first.next_cursor,
            )
        ]
        if len(chunks[0].items) < limit and first.next_cursor:
            second = await page(first.next_cursor)
            chunks.append(
                merge.Chunk(first.next_cursor, 0, second.items, second.next_cursor)
            )
        return chunks

    async def _call(
        self, account_id: str, operation: Callable[[MailProvider], Awaitable[T]]
    ) -> T:
        """Run one provider operation and keep the account's status in step
        with how it went."""
        return await self._accounts.observe(
            account_id, operation(self._accounts.provider(account_id))
        )


def _folder_of(message: MessageSummary) -> str:
    """The provider's folder of a message, empty where it names none."""
    return message.folder_ids[0] if message.folder_ids else ""


def _public(message: S, message_id: str, account_id: str) -> S:
    """A provider's message under our id, with its account."""
    return message.model_copy(update={"id": message_id, "account_id": account_id})


def _require_draft_right(
    access: Access, operation: str, account_id: str, draft: DraftMessage
) -> None:
    access.require(operation, account_id)
    if draft.reference is not None:
        # The draft quotes or carries the original, as a send would.
        access.require("get_message", account_id)


def _reference_header(reference: MessageReference) -> str:
    """What a draft keeps of its reference, e.g. ``reply msg_...``."""
    return f"{reference.action} {reference.message_id}"


def _delete_right(permanent: bool) -> str:
    return "delete_message_permanent" if permanent else "delete_message"


def _item(message_id: str, outcome: Any) -> BatchItemResult:
    if isinstance(outcome, MailboxApiError):
        return BatchItemResult(
            id=message_id,
            ok=False,
            error=ItemError(code=outcome.code, message=outcome.message),
        )
    summary = outcome if isinstance(outcome, MessageSummary) else None
    return BatchItemResult(id=message_id, ok=True, message=summary)
