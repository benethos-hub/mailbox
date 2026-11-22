"""The mailbox service: the only module that imports benethos_mailbox_client.

It offers what the agents need of the service and nothing else: its
version and whether that is tested, the change feed, the messages of the
last days for a backfill, the accounts, a message, a thread, the folders,
a keyword set or taken off, a move, and a folder made. There is no way
here to send, delete or trash, so the runtime cannot do any of it whatever
an agent asks. Which folder may be made is the runtime's to decide. Every
answer is turned into a record of :mod:`records`, and every failure into
an error of :mod:`errors`. See docs/mailbox-agents/concept/mailbox-service.md.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import AsyncIterator, Awaitable, Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from types import TracebackType
from typing import TypeVar

import httpx
from pydantic import ValidationError

from benethos_mailbox_client import (
    ApiError,
    ConfigurationError,
    MailboxClient,
    MailboxError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from benethos_mailbox_client import models as wire

from ..errors import (
    ChangesExpiredError,
    ConfigError,
    MailboxRefusedError,
    MailboxUnavailableError,
    MessageGoneError,
    ServiceVersionError,
)
from ..records import (
    EVENTS,
    Address,
    Attachment,
    Event,
    FolderRef,
    MailMessage,
    MessageRef,
    Thread,
)

__all__ = ["TESTED", "Mailbox", "connect", "is_tested", "line_names", "shown"]

T = TypeVar("T")

# The size of one page of the feed and of a message list.
_PAGE = 200

# The lines of the mailbox service this package is tested against, each as
# its lowest release, the newest last. A line is the minor version while
# the major is 0, where a minor release may change what the service does,
# and the major version after that. The newest one is the pin of the client
# in pyproject.toml and the line of the image of containers/live, which
# packages/mailbox-agents/tests/sources/test_service_version.py holds equal. A line is
# added by a change of its own, see docs/mailbox-agents/concept/mailbox-service.md.
TESTED: tuple[tuple[int, int, int], ...] = ((0, 8, 0), (0, 9, 0), (0, 10, 0))

# A release: three numbers and at most a local part after a "+". A
# pre-release such as 0.8.0rc1 or 0.8.1.dev3 is none, also of a later
# patch: a line counts releases.
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?")

# How each refusal of a service outside the lines ends.
_RUN_TESTED = ": run a release of the agents that is tested against that service"


def _within(found: tuple[int, int, int], floor: tuple[int, int, int]) -> bool:
    """Whether ``found`` is in the line of ``floor`` and not below it."""
    if floor[0] == 0:
        return found[:2] == floor[:2] and found[2] >= floor[2]
    return found[0] == floor[0] and found[1:] >= floor[1:]


def is_tested(version: str) -> bool:
    """Whether ``version`` of the service is in a line of :data:`TESTED`.
    It is a release, three numbers with at most a local part after them,
    or in no line."""
    match = _VERSION.fullmatch(version)
    if match is None:
        return False
    major, minor, patch = (int(part) for part in match.groups())
    return any(_within((major, minor, patch), floor) for floor in TESTED)


def shown(version: str) -> str:
    """``version`` as the service names it, cut for a line of text: a
    service may answer anything there."""
    return version[:40]


def line_names() -> str:
    """The lines of :data:`TESTED` in words, for a person."""
    return " and ".join(
        f"{floor[0]}.{floor[1]} from {floor[0]}.{floor[1]}.{floor[2]}"
        if floor[0] == 0
        else f"{floor[0]} from {floor[0]}.{floor[1]}.{floor[2]}"
        for floor in TESTED
    )


async def _call(pending: Awaitable[T]) -> T:
    """Await a call of the client and translate what it raises."""
    try:
        return await pending
    except ApiError as exc:
        if exc.status == 410 and exc.code == "changes_expired":
            raise ChangesExpiredError("the feed state has expired") from None
        if exc.status >= 500 or exc.status == 429:
            raise MailboxUnavailableError(
                f"the mailbox service answered {exc.status} ({exc.code})"
            ) from None
        refused = MessageGoneError if exc.status == 404 else MailboxRefusedError
        raise refused(
            f"the mailbox service refused: {exc.code}",
            status=exc.status,
            reason=exc.code,
        ) from None
    except (ServiceUnavailableError, ServiceTimeoutError) as exc:
        raise MailboxUnavailableError(
            f"the mailbox service is away ({type(exc).__name__})"
        ) from None
    except ConfigurationError as exc:
        raise ConfigError(f"the mailbox service: {exc}") from None
    except MailboxError as exc:
        raise MailboxUnavailableError(
            f"the mailbox service failed ({type(exc).__name__})"
        ) from None
    except RecursionError:
        # The client reads JSON nested too deep for the parser, and catches
        # only a ValueError of it.
        raise MailboxUnavailableError(
            "the mailbox service answered JSON nested too deep"
        ) from None


def _sound(value: str) -> str:
    """``value`` with each lone surrogate replaced by U+FFFD. One comes from
    the JSON escape of half a pair, and it cannot be encoded as UTF-8: a
    request to the gateway or a write to the state file would raise
    outside every error of this package."""
    return "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in value)


def _sound_or_none(value: str | None) -> str | None:
    return None if value is None else _sound(value)


@contextmanager
def _as_described() -> Iterator[None]:
    """Build a record of what the service answered. The client passes the
    fields of a message on unchecked, so a value of another type raises
    while the record is built. That is a refusal, as for an answer the
    client finds unexpected: the message counts an attempt. Its text never
    holds the value, which may be a part of a mail."""
    try:
        yield
    except (ValidationError, TypeError):
        raise MailboxRefusedError(
            "the answer is not what the API describes", reason="unexpected_response"
        ) from None


def _address(found: wire.Address | None) -> Address | None:
    if not found:
        return None
    return Address(email=_sound(found.email), name=_sound_or_none(found.name))


def _addresses(found: Iterable[wire.Address]) -> tuple[Address, ...]:
    return tuple(
        Address(email=_sound(a.email), name=_sound_or_none(a.name)) for a in found
    )


class Mailbox:
    """One agent's view of the mailbox service, over one client."""

    def __init__(self, client: MailboxClient) -> None:
        self._client = client
        self._folders: dict[str, dict[str, FolderRef]] = {}

    async def __aenter__(self) -> Mailbox:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- the service itself ---------------------------------------------------------

    async def version(self) -> str:
        """The version the service names at ``/health``, which it answers
        without a right and counts against no limit. Raises
        :class:`ServiceVersionError` when it names none, or refuses: a
        service that does not answer as a tested one is outside the lines."""
        try:
            found = await _call(self._client.health())
        except MailboxRefusedError:
            raise ServiceVersionError(
                "the mailbox service names no version at /health, and this "
                f"package is tested against {line_names()}{_RUN_TESTED}"
            ) from None
        return found.version

    async def ensure_tested(self) -> str:
        """The version of the service, once it is in a tested line. Raises
        :class:`ServiceVersionError` for any other."""
        found = await self.version()
        if not is_tested(found):
            raise ServiceVersionError(
                f"the mailbox service runs {shown(found)!r}, and this package "
                f"is tested against {line_names()}{_RUN_TESTED}"
            )
        return found

    # -- the change feed ----------------------------------------------------------

    async def start(self, accounts: list[str] | None = None) -> str:
        """The state to read the feed from, from now on."""
        found = await _call(self._client.list_all_changes(accounts=accounts or None))
        return found.state

    async def changes(
        self, since: str, accounts: list[str] | None = None
    ) -> tuple[list[Event], str]:
        """Every change after ``since``, pages followed, and the new state.
        Raises :class:`ChangesExpiredError` for a state the service no
        longer keeps changes for."""
        events: list[Event] = []
        state = since
        while True:
            found = await _call(
                self._client.list_all_changes(
                    accounts=accounts or None, since=state, limit=_PAGE
                )
            )
            events += [
                Event(
                    type=change.type,
                    ref=MessageRef(account_id=change.account_id, message_id=change.id),
                    at=change.at,
                )
                for change in found.changes
                if change.type in EVENTS
            ]
            state = found.state
            if not found.more:
                return events, state

    async def recent(
        self,
        since: date,
        accounts: list[str] | None = None,
        *,
        roles: tuple[str, ...],
    ) -> list[MessageRef]:
        """The messages from ``since`` on in the folders of ``roles``,
        received or sent, for a backfill. The service lists the inbox alone when
        no folder is named, so each role is asked for by itself."""
        refs: dict[MessageRef, None] = {}
        for role in roles:
            cursor: str | None = None
            while True:
                page = await _call(
                    self._client.list_all_messages(
                        accounts=accounts or None,
                        folder=role,
                        after=since.isoformat(),
                        limit=_PAGE,
                        cursor=cursor,
                    )
                )
                for item in page.items:
                    if item.account_id:
                        refs[
                            MessageRef(account_id=item.account_id, message_id=item.id)
                        ] = None
                cursor = page.next_cursor
                if not cursor:
                    break
        return list(refs)

    async def recent_in(
        self, account_id: str, folder_id: str, since: date
    ) -> list[MessageRef]:
        """The messages from ``since`` on in one folder of one account, named
        by its id: the service lists a folder by its id per account, not by
        its path and not across accounts (measured 2026-11-18)."""
        refs: list[MessageRef] = []
        cursor: str | None = None
        while True:
            page = await _call(
                self._client.list_messages(
                    account_id,
                    folder=folder_id,
                    after=since.isoformat(),
                    limit=_PAGE,
                    cursor=cursor,
                )
            )
            refs += [
                MessageRef(account_id=account_id, message_id=item.id)
                for item in page.items
            ]
            cursor = page.next_cursor
            if not cursor:
                return refs

    # -- reading ---------------------------------------------------------------------

    async def accounts(self) -> tuple[str, ...]:
        """The ids of the accounts the user is granted, as ``get_me``
        answers them. ``list_accounts`` answers a user with ``mail.read``
        and ``mail.write`` alone no account (measured 2026-11-18)."""
        found = await _call(self._client.get_me())
        return tuple(account.id for account in found.accounts)

    async def folders(
        self, account_id: str, *, fresh: bool = False
    ) -> dict[str, FolderRef]:
        """The folders of an account by id, each with its path. Kept until
        ``fresh`` asks for them again."""
        if fresh or account_id not in self._folders:
            found = await _call(self._client.list_folders(account_id))
            self._folders[account_id] = _with_paths(found)
        return self._folders[account_id]

    async def folder_at(self, account_id: str, path: str) -> FolderRef | None:
        """The folder at ``path``, ``/`` between the names, asked once more
        of the service before it counts as missing."""
        for fresh in (False, True):
            for folder in (await self.folders(account_id, fresh=fresh)).values():
                if folder.path == path:
                    return folder
        return None

    async def _refs(self, account_id: str, ids: list[str]) -> tuple[FolderRef, ...]:
        known = await self.folders(account_id)
        if any(i not in known for i in ids):
            known = await self.folders(account_id, fresh=True)
        return tuple(known[i] for i in ids if i in known)

    async def message(self, ref: MessageRef) -> MailMessage:
        found = await _call(self._client.get_message(ref.account_id, ref.message_id))
        with _as_described():
            return MailMessage(
                ref=ref,
                thread_id=found.thread_id,
                folders=await self._refs(ref.account_id, found.folder_ids),
                subject=_sound_or_none(found.subject),
                sender=_address(found.sender),
                to=_addresses(found.to),
                cc=_addresses(found.cc),
                date=found.date,
                received=found.received,
                keywords=tuple(found.keywords),
                text=_sound(found.text_body or ""),
                attachments=tuple(
                    Attachment(
                        filename=_sound_or_none(a.filename),
                        content_type=a.content_type,
                        size=a.size,
                        inline=a.inline,
                    )
                    for a in found.attachments
                ),
                message_id_header=found.message_id_header,
                in_reply_to=found.in_reply_to,
            )

    async def thread(self, account_id: str, thread_id: str) -> Thread:
        """A thread, its messages oldest first, each without its text."""
        found = await _call(self._client.get_thread(account_id, thread_id))
        with _as_described():
            messages = []
            for item in found.messages:
                messages.append(
                    MailMessage(
                        ref=MessageRef(account_id=account_id, message_id=item.id),
                        thread_id=item.thread_id,
                        folders=await self._refs(account_id, item.folder_ids),
                        subject=_sound_or_none(item.subject),
                        sender=_address(item.sender),
                        to=_addresses(item.to),
                        date=item.date,
                        received=item.received,
                        keywords=tuple(item.keywords),
                    )
                )
            return Thread(id=found.id, messages=tuple(messages))

    # -- the actions -------------------------------------------------------------------

    async def create_folder(self, account_id: str, path: str) -> FolderRef:
        """Make the folder at ``path``, below a parent that exists. Answers
        it with its path. Its parent missing is a refusal, as is a name the
        service already knows in the same case. Another case is not
        refused by the service (measured 2026-11-18), the caller compares."""
        parent_path, _, name = path.rpartition("/")
        parent_id: str | None = None
        if parent_path:
            parent = await self.folder_at(account_id, parent_path)
            if parent is None:
                raise MailboxRefusedError(
                    "the parent folder does not exist", reason="parent_missing"
                )
            parent_id = parent.id
        made = await _call(self._client.create_folder(account_id, name, parent_id))
        known = await self.folders(account_id, fresh=True)
        if made.id in known:
            return known[made.id]
        return FolderRef(id=made.id, name=_sound(made.name), role=made.role, path=path)

    async def add_keyword(self, ref: MessageRef, keyword: str) -> None:
        await _call(
            self._client.update_message(
                ref.account_id, ref.message_id, add_keywords=[keyword]
            )
        )

    async def remove_keyword(self, ref: MessageRef, keyword: str) -> None:
        await _call(
            self._client.update_message(
                ref.account_id, ref.message_id, remove_keywords=[keyword]
            )
        )

    async def move(self, ref: MessageRef, folder_id: str) -> None:
        """Move a message into the folder ``folder_id``, out of the others."""
        await _call(
            self._client.update_message(
                ref.account_id, ref.message_id, folder_ids=[folder_id]
            )
        )


def _with_paths(found: list[wire.Folder]) -> dict[str, FolderRef]:
    by_id = {folder.id: folder for folder in found}

    def path(folder: wire.Folder) -> str:
        names = [_sound(folder.name)]
        seen = {folder.id}
        parent = by_id.get(folder.parent_id) if folder.parent_id else None
        while parent is not None and parent.id not in seen:
            names.append(_sound(parent.name))
            seen.add(parent.id)
            parent = by_id.get(parent.parent_id) if parent.parent_id else None
        return "/".join(reversed(names))

    return {
        folder.id: FolderRef(
            id=folder.id,
            name=_sound(folder.name),
            role=folder.role,
            path=path(folder),
        )
        for folder in found
    }


@asynccontextmanager
async def connect(
    base_url: str,
    token: str,
    *,
    allow_http: bool = False,
    verify: ssl.SSLContext | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[Mailbox]:
    """A :class:`Mailbox` over a client of its own, closed on the way out.

    Without a transport of a test, the client gets one that reads no proxy
    and no certificate setting from the environment, as the gateway does.
    ``verify`` replaces the roots of certifi, as an own CA needs.
    """
    if transport is None:
        transport = httpx.AsyncHTTPTransport(
            trust_env=False, verify=True if verify is None else verify
        )
    try:
        client = MailboxClient(
            base_url=base_url, token=token, transport=transport, allow_http=allow_http
        )
    except ConfigurationError as exc:
        raise ConfigError(f"the mailbox service: {exc}") from None
    async with Mailbox(client) as mailbox:
        yield mailbox
