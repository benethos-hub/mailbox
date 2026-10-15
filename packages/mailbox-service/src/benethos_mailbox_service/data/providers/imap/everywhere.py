"""The folder ``all`` of a server without ``\\All`` (UNIFORM 6.5): one
SEARCH in every folder but the trash and junk, the hits merged newest
first by when they arrived. The list ``\\All`` would give, one SEARCH
per folder and page slower.

Of each folder only its newest hits below its place are dated, by
INTERNALDATE alone, and only those the page keeps are read. Each folder
is taken in its own order, newest UID first, and of the folders' next
hits the newest comes first, as the list across accounts merges: a mail
filed late with an old date never makes the folder skip one, though it
can stand on a later page than its date says. Each page is newest
first. The cursor holds, per folder with hits left, its UIDVALIDITY and
the UID below which its next page looks. A folder it does not name has
none left.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ....common import opaque
from ....errors import BadRequestError
from ...models import MessageFilter, MessageSummary, Page
from .. import rules
from . import mappers
from .mailbox import Mailbox
from .messages import criteria

_PREFIX = "a_"


@dataclass(frozen=True)
class _Place:
    uidvalidity: int
    before_uid: int | None


@dataclass(frozen=True)
class _Hit:
    when: datetime | None
    folder: str
    uid: int

    def newest_first(self) -> tuple[bool, float, str, int]:
        stamp = -self.when.timestamp() if self.when else 0.0
        return (self.when is None, stamp, self.folder, -self.uid)


def list_all(
    box: Mailbox, limit: int, cursor: str | None, search: MessageFilter | None
) -> Page[MessageSummary]:
    search = search or MessageFilter()
    scope = rules.cursor_scope(mappers.ALL, search)
    places = _places(cursor, scope) if cursor else None
    streams: dict[str, list[_Hit]] = {}
    found: dict[str, tuple[int, list[int]]] = {}
    for folder in _folders(box):
        place = places.get(folder) if places is not None else _Place(0, None)
        if place is None:
            continue
        validity = box.session.select(folder)
        if places is not None and place.uidvalidity != validity:
            raise BadRequestError("a folder changed on the server: start again")
        uids = box.session.messages.search(criteria(search, place.before_uid))
        newest = uids[-limit:]
        dates = box.session.messages.fetch_dates(newest)
        streams[folder] = [
            _Hit(dates.get(uid), folder, uid) for uid in reversed(newest)
        ]
        found[folder] = (validity, uids)
    page = _merged(streams, limit)
    items = _summaries(box, page, {f: v for f, (v, _) in found.items()})
    left: dict[str, list[int]] = {}
    for folder, (validity, uids) in found.items():
        taken = [h.uid for h in page if h.folder == folder]
        lowest = min(taken) if taken else (uids[-1] + 1 if uids else 0)
        if any(uid < lowest for uid in uids):
            left[folder] = [validity, lowest]
    return Page[MessageSummary](
        items=items,
        next_cursor=opaque.encode(_PREFIX, [scope, left]) if left else None,
    )


def _merged(streams: dict[str, list[_Hit]], limit: int) -> list[_Hit]:
    """Up to ``limit`` hits, each folder's taken from its top, the newest
    of the folders' next ones first. The page sorted newest first."""
    page: list[_Hit] = []
    while len(page) < limit:
        heads = [hits[0] for hits in streams.values() if hits]
        if not heads:
            break
        best = min(heads, key=_Hit.newest_first)
        page.append(streams[best.folder].pop(0))
    return sorted(page, key=_Hit.newest_first)


def _folders(box: Mailbox) -> list[str]:
    """The server's names of the folders ``all`` lists."""
    return [
        mappers.folder_name(f.id)
        for f in box.listed()
        if f.role not in mappers.OUTSIDE_ALL
    ]


def _summaries(
    box: Mailbox, page: list[_Hit], validities: dict[str, int]
) -> list[MessageSummary]:
    """The page read folder by folder, in its order."""
    read: dict[tuple[str, int], MessageSummary] = {}
    for folder in dict.fromkeys(h.folder for h in page):
        uids = [h.uid for h in page if h.folder == folder]
        box.session.select(folder)
        for message in box.session.messages.fetch_headers(uids):
            if message.uid:
                summary = mappers.summary(message, folder, validities[folder])
                read[(folder, int(message.uid))] = summary
    return [read[(h.folder, h.uid)] for h in page if (h.folder, h.uid) in read]


def _places(cursor: str, scope: str) -> dict[str, _Place]:
    try:
        value = opaque.decode(_PREFIX, cursor)
    except ValueError:
        raise rules.invalid_cursor() from None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or value[0] != scope
        or not isinstance(value[1], dict)
    ):
        raise rules.invalid_cursor()
    places: dict[str, _Place] = {}
    for folder, place in value[1].items():
        if (
            not isinstance(place, list)
            or len(place) != 2
            or not all(isinstance(n, int) and not isinstance(n, bool) for n in place)
        ):
            raise rules.invalid_cursor()
        places[folder] = _Place(place[0], place[1])
    return places
