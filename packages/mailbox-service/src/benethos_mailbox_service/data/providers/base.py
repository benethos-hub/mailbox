"""The contract of the provider adapters: ``Reads``, which every adapter
fulfils, and one protocol for each thing an adapter may do beyond it."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import SecretStr

from ...errors import MailboxServiceError
from ..mail import ThreadHeaders
from ..models import (
    Abilities,
    AttachmentContent,
    Capability,
    Folder,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)

# Hands an adapter one stored credential by field name, decrypted at the
# moment of the call. Adapters call it right before a login and keep nothing.
CredentialReader = Callable[[str], SecretStr]

# An account's connection settings: host, port, security and the like.
# Never a secret: those come through the ``CredentialReader``.
ProviderSettings = Mapping[str, str | int | bool]


class TokenSource(Protocol):
    """Hands an OAuth adapter a valid access token, refreshed when it runs
    out. The token lives in memory only. What keeps it valid is stored by
    whoever made the source."""

    async def access_token(self) -> SecretStr:
        """A token valid for at least another minute."""
        ...

    def reject(self) -> None:
        """The provider refused the token before it ran out, e.g. after a
        revocation: the next call fetches a new one."""
        ...

    def forget_refusal(self) -> None:
        """A refresh the provider refused is asked again with the next call,
        e.g. when an account is verified. Until then it is not."""
        ...


@dataclass(frozen=True)
class ChangedMessage:
    """A message a folder reports as new or changed."""

    id: str
    created: datetime | None = None


@dataclass(frozen=True, slots=True)
class FolderChanges:
    """What changed in one folder since a token, and the token to ask
    from next time."""

    token: str
    changed: list[ChangedMessage] = field(default_factory=list)
    # Deleted, or moved out of the folder.
    removed: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ThreadMessages:
    """The messages of a thread, oldest first: the newest ones where the
    thread holds more than were asked for."""

    messages: list[MessageSummary]
    # The thread holds more messages than these.
    truncated: bool = False


@runtime_checkable
class Reads(Protocol):
    """What every adapter does: one connected account at one provider,
    read, and what the sync worker asks of it.

    Message ids are the provider's own. Without ``stable_ids`` they name a
    place, and the domain maps them to ids that survive a move. What an
    adapter does beyond reading is a protocol of its own below. An adapter
    implements those it may be able to do. What its account can do follows
    from what the server offers (``abilities``), and the domain checks that
    before it calls the adapter.
    """

    # A message keeps its id when it is moved. Without it the domain keeps
    # an id mapping (CONCEPT 4.1).
    stable_ids: bool

    async def abilities(self) -> Abilities:
        """What the account can do, as its server answers now: asked when
        the account is connected or verified, and again when an answer of
        the server contradicts what was stored (UNIFORM R4). Logs in where
        it must."""
        ...

    async def list_folders(self) -> list[Folder]: ...

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        """Newest first. ``search`` narrows the list. A cursor belongs to
        the same folder and search. Without a folder: every folder of the
        account where the provider can list across them (Microsoft), else
        the inbox (IMAP)."""
        ...

    async def get_message(self, message_id: str) -> Message: ...

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent: ...

    async def get_raw(self, message_id: str) -> bytes:
        """The message source as RFC 822 bytes."""
        ...

    # --- for the sync worker ---------------------------------------------------

    async def folder_states(self) -> dict[str, str]:
        """Every folder that holds messages, with an opaque state that
        changes whenever a message arrives in it or leaves it."""
        ...

    async def folder_contents(self, folder_id: str) -> list[str]:
        """The ids of every message in the folder."""
        ...

    async def message_headers(self, message_ids: list[str]) -> dict[str, ThreadHeaders]:
        """The ``Message-ID`` of each message, and where the adapter reads
        them, the headers that tie it to its conversation. Messages that are
        gone are left out."""
        ...

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """Those of ``message_ids``, all in the folder, whose flags changed
        since the folder had the state ``since``. Empty where the provider
        cannot tell."""
        ...

    async def verify(self) -> None:
        """Log in afresh and forget an earlier rejected login. Raises
        ``ProviderAuthError`` if the credential does not work."""
        ...

    async def close(self) -> None: ...


@runtime_checkable
class Deletes(Protocol):
    """Deletes messages: into the trash where the account has one, or for
    good. A POP3 mailbox does this and nothing else of ``Writes``."""

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        """Into the trash, or for good. Per id the message in the trash
        where it is known, None when it is gone or not found there at once,
        or why not. A failed login or connection raises instead, or, once
        some are done, is the outcome of the rest."""
        ...


@runtime_checkable
class Writes(Deletes, Protocol):
    """Changes messages and folders: read state, stars, keywords, moves,
    and the folders themselves."""

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        """Change flags and keywords, or move, of every message. Per id the
        message as it is now (after a move its id names the new place), or
        why not. A failed login or connection raises instead, or, once some
        are done, is the outcome of the rest."""
        ...

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        """A new folder, subscribed where the provider knows subscriptions."""
        ...

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        """Rename or move. The folder's id may change with its name."""
        ...

    async def delete_folder(self, folder_id: str) -> None: ...


@runtime_checkable
class Drafts(Protocol):
    """Keeps drafts.

    A draft id names a message the provider keeps as a draft, on IMAP one
    in the folder with the drafts role. Any other id is not found, so that
    the draft operations reach drafts only."""

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]: ...

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        """Store a composed draft, then remove the draft it ``replaces``.
        The draft as stored. Its id may differ from ``replaces``."""
        ...

    async def get_draft(self, draft_id: str) -> bytes:
        """The draft's source as RFC 822 bytes."""
        ...

    async def delete_draft(self, draft_id: str) -> None:
        """Remove a draft for good, as mail clients do once it is sent."""
        ...


@runtime_checkable
class Sends(Protocol):
    """Sends mail. IMAP and POP3 send only where the account names an
    SMTP server, and their ``abilities`` say so."""

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Send a composed message, and keep a copy where the provider does
        not do that itself. Once the message is out it does not fail: a
        client would send again."""
        ...


@runtime_checkable
class Watches(Protocol):
    """Hears of changes as the server reports them, without polling."""

    async def wait_for_change(self, timeout: float) -> bool:
        """Wait until the server reports a change in the inbox, at most
        ``timeout`` seconds. True if it did."""
        ...


@runtime_checkable
class Deltas(Protocol):
    """Tells what changed in a folder since a token, instead of the sync
    comparing the folder's contents."""

    async def folder_changes(
        self, folder_id: str, token: str | None, since: datetime | None = None
    ) -> FolderChanges:
        """What changed in the folder since ``token``. Without a token every
        message counts as changed. A token the provider no longer knows
        raises ``ChangesExpiredError``. Without a token but with ``since``,
        after such an error, the messages that arrived since then carry
        ``created``."""
        ...


@runtime_checkable
class Threads(Protocol):
    """Keeps the threads of its messages, each message's ``thread_id``
    the provider's own."""

    async def thread_messages(self, thread_id: str, limit: int) -> ThreadMessages:
        """The messages of a thread in every folder, at most ``limit``.
        Raises ``NotFoundError`` for a thread that is not there."""
        ...


@runtime_checkable
class Summaries(Protocol):
    """Reads the summaries of messages named by id, wherever they are. The
    domain needs it for the threads it keeps itself (IMAP)."""

    async def summaries(self, message_ids: list[str]) -> dict[str, MessageSummary]:
        """The summary of each message that is there, by id."""
        ...


# The protocols an adapter implements where its account may have a
# capability, any one of them. The domain threads an account of its own
# where the adapter reads summaries.
PROTOCOLS: Mapping[Capability, tuple[type, ...]] = {
    Capability.READ_STATE: (Writes,),
    Capability.STARS: (Writes,),
    Capability.KEYWORDS: (Writes,),
    Capability.FOLDERS: (Writes,),
    Capability.MOVE: (Writes,),
    Capability.LABELS: (Writes,),
    Capability.TRASH: (Deletes,),
    Capability.PURGE: (Deletes,),
    Capability.DRAFTS: (Drafts,),
    Capability.SEND: (Sends,),
    Capability.SENT_COPY: (Sends,),
    Capability.REFUSED: (Sends,),
    Capability.PUSH: (Watches,),
    Capability.THREADS: (Threads, Summaries),
}
