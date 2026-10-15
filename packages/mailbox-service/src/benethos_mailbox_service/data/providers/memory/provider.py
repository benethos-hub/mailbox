"""An in-memory provider for tests and local development. No network."""

from __future__ import annotations

from ....errors import (
    ConflictError,
    MailboxServiceError,
    missing,
    missing_message,
)
from ...mail import ThreadHeaders, convert, parse
from ...models import (
    Abilities,
    AttachmentContent,
    Capability,
    Folder,
    FolderRole,
    Mark,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
    received_or_written,
)
from .. import rules


class MemoryProvider:
    stable_ids = True

    def __init__(
        self,
        folders: list[Folder] | None = None,
        messages: list[Message] | None = None,
        abilities: Abilities | None = None,
    ) -> None:
        """``abilities``: what the account answers it can do, by default
        what its folders allow."""
        self.given = abilities
        # Whether a message may sit in several folders.
        self.labels = False
        self.folders = folders or [
            Folder(id="inbox", name="Inbox", role=FolderRole.INBOX),
            Folder(id="sent", name="Sent", role=FolderRole.SENT),
            Folder(id="drafts", name="Drafts", role=FolderRole.DRAFTS),
        ]
        self.messages = messages or []
        self.attachment_data: dict[tuple[str, str], bytes] = {}
        # The source of every stored draft, by id.
        self.raws: dict[str, bytes] = {}
        self._drafts_saved = 0
        # (sender, recipients, raw) of every send, for tests.
        self.outbox: list[tuple[str, list[str], bytes]] = []

    async def list_folders(self) -> list[Folder]:
        return list(self.folders)

    async def list_messages(
        self,
        folder_id: str,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        search = search or MessageFilter()
        found = [
            m
            for m in self.messages
            if _within(m, folder_id, self.folders) and _matches(m, search)
        ]
        try:
            start = int(cursor) if cursor else 0
        except ValueError:
            raise rules.invalid_cursor() from None
        chunk = found[start : start + limit]
        more = start + limit < len(found)
        return Page[MessageSummary](
            items=[MessageSummary.model_validate(m.model_dump()) for m in chunk],
            next_cursor=str(start + limit) if more else None,
        )

    async def get_message(self, message_id: str) -> Message:
        for message in self.messages:
            if message.id == message_id:
                return message
        raise missing_message(message_id)

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        message = await self.get_message(message_id)
        for attachment in message.attachments:
            if attachment.id == attachment_id:
                data = self.attachment_data.get((message_id, attachment_id), b"")
                return AttachmentContent(
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    data=data,
                )
        raise missing("attachment", attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        message = await self.get_message(message_id)
        if message.id in self.raws:
            return self.raws[message.id]
        body = message.text_body or ""
        return f"Subject: {message.subject or ''}\r\n\r\n{body}".encode()

    async def _update_one(
        self, message_id: str, changes: MessageUpdate
    ) -> MessageSummary:
        message = await self.get_message(message_id)
        fields = changes.model_dump(include={"unread", "starred"}, exclude_none=True)
        rules.move_target(changes, labels=self.labels)
        known = {folder.id for folder in self.folders}
        for folder_id in changes.named_folders():
            if folder_id not in known:
                raise missing("folder", folder_id)
        folders = changes.folders_after(message.folder_ids)
        if folders == []:
            raise rules.no_folder_left()
        if folders is not None:
            fields["folder_ids"] = folders
        keywords = changes.keywords_after(message.keywords)
        if keywords is not None:
            fields["keywords"] = sorted(keywords)
        updated = message.model_copy(update=fields)
        self.messages[self.messages.index(message)] = updated
        return MessageSummary.model_validate(updated.model_dump())

    async def _delete_one(
        self, message_id: str, permanent: bool
    ) -> MessageSummary | None:
        message = await self.get_message(message_id)
        if permanent:
            self.messages.remove(message)
            return None
        trash = self._role_folder(FolderRole.TRASH)
        if trash in message.folder_ids:
            raise rules.in_trash_already()
        moved = message.model_copy(update={"folder_ids": [trash]})
        self.messages[self.messages.index(message)] = moved
        return MessageSummary.model_validate(moved.model_dump())

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Records what was sent in ``outbox`` and keeps a copy in the sent
        folder."""
        self.outbox.append((sender, list(recipients), raw))
        sent = next((f.id for f in self.folders if f.role is FolderRole.SENT), None)
        if sent is None:
            return SentMessage()
        parsed = parse.ParsedMessage(raw)
        copy = Message(
            id=f"sent_{len(self.outbox)}",
            folder_ids=[sent],
            subject=parsed.subject,
            message_id_header=parsed.message_id,
        )
        self.messages.append(copy)
        return SentMessage(sent_copy=MessageSummary.model_validate(copy.model_dump()))

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await self.list_messages(
            self._drafts_folder(), limit=limit, cursor=cursor
        )

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        drafts = self._drafts_folder()
        old = self._draft(replaces) if replaces else None
        parsed = parse.ParsedMessage(raw)
        self._drafts_saved += 1
        draft = Message.model_validate(
            {
                **convert.summary_fields(parsed),
                **convert.message_fields(parsed),
                # Stable ids: a replaced draft keeps its id.
                "id": old.id if old else f"draft_{self._drafts_saved}",
                "folder_ids": [drafts],
                "keywords": ["$draft"],
            }
        )
        if old is not None:
            self.messages.remove(old)
        self.messages.append(draft)
        self.raws[draft.id] = raw
        return MessageSummary.model_validate(draft.model_dump())

    async def get_draft(self, draft_id: str) -> bytes:
        return self.raws[self._draft(draft_id).id]

    async def delete_draft(self, draft_id: str) -> None:
        draft = self._draft(draft_id)
        self.messages.remove(draft)
        self.raws.pop(draft.id, None)

    def _drafts_folder(self) -> str:
        return self._role_folder(FolderRole.DRAFTS)

    def _role_folder(self, role: FolderRole) -> str:
        return rules.require_role_folder(self.folders, role).id

    def _draft(self, draft_id: str) -> Message:
        drafts = self._drafts_folder()
        for message in self.messages:
            if message.id == draft_id and drafts in message.folder_ids:
                return message
        raise missing("draft", draft_id)

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        if parent_id is not None:
            self._folder(parent_id)
        if any(f.name == name and f.parent_id == parent_id for f in self.folders):
            raise ConflictError(f"a folder {name} exists there already")
        folder = Folder(
            id=f"folder_{len(self.folders)}", name=name, parent_id=parent_id
        )
        self.folders.append(folder)
        return folder

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        folder = self._folder(folder_id)
        if parent_id is not None:
            self._folder(parent_id)
        updated = folder.model_copy(update={"name": name, "parent_id": parent_id})
        self.folders[self.folders.index(folder)] = updated
        return updated

    async def delete_folder(self, folder_id: str) -> None:
        self.folders.remove(self._folder(folder_id))

    def _folder(self, folder_id: str) -> Folder:
        for folder in self.folders:
            if folder.id == folder_id:
                return folder
        raise missing("folder", folder_id)

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await rules.per_id(
            message_ids, lambda message_id: self._update_one(message_id, changes)
        )

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await rules.per_id(
            message_ids, lambda message_id: self._delete_one(message_id, permanent)
        )

    async def folder_states(self) -> dict[str, str]:
        return {
            f.id: ",".join(m.id for m in self.messages if f.id in m.folder_ids)
            for f in self.folders
        }

    async def folder_contents(self, folder_id: str) -> list[str]:
        return [m.id for m in self.messages if folder_id in m.folder_ids]

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        return []

    async def message_headers(self, message_ids: list[str]) -> dict[str, ThreadHeaders]:
        wanted = set(message_ids)
        return {
            m.id: ThreadHeaders(m.message_id_header)
            for m in self.messages
            if m.id in wanted
        }

    async def abilities(self) -> Abilities:
        if self.given is not None:
            return self.given
        roles = {folder.role for folder in self.folders}
        found = {
            Capability.READ_STATE,
            Capability.STARS,
            Capability.KEYWORDS,
            Capability.FOLDERS,
            Capability.MOVE,
            Capability.PURGE,
            Capability.SEARCH,
            Capability.SEND,
        }
        for role, capability in (
            (FolderRole.TRASH, Capability.TRASH),
            (FolderRole.DRAFTS, Capability.DRAFTS),
            (FolderRole.SENT, Capability.SENT_COPY),
        ):
            if role in roles:
                found.add(capability)
        if self.labels:
            found.add(Capability.LABELS)
        return Abilities.of(found, written=set(Mark))

    async def verify(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _within(message: Message, folder_id: str, folders: list[Folder]) -> bool:
    """Whether the message is in the folder. The folder with the role
    ``all`` holds every message but those in the trash and junk."""
    roles = {f.id: f.role for f in folders}
    if roles.get(folder_id) is not FolderRole.ALL:
        return folder_id in message.folder_ids
    outside = (FolderRole.TRASH, FolderRole.JUNK)
    return not any(roles.get(f) in outside for f in message.folder_ids)


def _matches(message: Message, search: MessageFilter) -> bool:
    """Case-insensitive substrings, as IMAP SEARCH compares."""

    def has(value: str | None, *fields: str | None) -> bool:
        return value is None or any(value.lower() in (f or "").lower() for f in fields)

    sender = message.sender
    when = received_or_written(message)
    day = when.date() if when else None
    return (
        has(search.text, message.subject, message.text_body)
        and has(
            search.sender,
            sender.email if sender else None,
            sender.name if sender else None,
        )
        and has(search.to, *(a.email for a in message.to))
        and has(search.subject, message.subject)
        and (search.after is None or (day is not None and day >= search.after))
        and (search.before is None or (day is not None and day < search.before))
        and search.flags_match(message)
    )
