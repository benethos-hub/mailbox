"""What an account can do beyond reading, asked before its adapter is
asked to do it (docs/UNIFORM.md, rule R3).

``NEEDS`` is the one table of what each operation needs, and
``lacking`` names what an account's stored abilities leave out. The
domain answers ``501 not_supported`` for it, the same for every kind of
account. An adapter implements only the protocols of ``data.providers``
it can, and the functions below hand them out, answering ``501`` too
where one is missing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ...data.models import (
    Abilities,
    Capability,
    Mark,
    MessageFilter,
    MessageUpdate,
)
from ...data.providers import (
    Deletes,
    Deltas,
    Drafts,
    Reads,
    Sends,
    Summaries,
    Threads,
    Watches,
    Writes,
)
from ...errors import NotSupportedError


@dataclass(frozen=True, slots=True)
class Needs:
    """What one call of an operation needs of the account."""

    capabilities: frozenset[Capability] = frozenset()
    # The marks it sets or takes off.
    marks: frozenset[Mark] = frozenset()

    def __or__(self, other: Needs) -> Needs:
        return Needs(self.capabilities | other.capabilities, self.marks | other.marks)


def needs(*capabilities: Capability) -> Needs:
    return Needs(frozenset(capabilities))


NOTHING = Needs()

# What each operation on one account needs, by its operationId, where that
# does not depend on the request. Reading needs nothing.
NEEDS: Mapping[str, Needs] = {
    "create_folder": needs(Capability.FOLDERS),
    "update_folder": needs(Capability.FOLDERS),
    "delete_folder": needs(Capability.FOLDERS),
    "list_threads": needs(Capability.THREADS),
    "get_thread": needs(Capability.THREADS),
    "send_message": needs(Capability.SEND),
    "list_drafts": needs(Capability.DRAFTS),
    "create_draft": needs(Capability.DRAFTS),
    "update_draft": needs(Capability.DRAFTS),
    "delete_draft": needs(Capability.DRAFTS),
    "send_draft": needs(Capability.DRAFTS, Capability.SEND),
}

# What an account lacks, in words: "this account cannot ...".
_CANNOT: Mapping[Capability, str] = {
    Capability.READ_STATE: "keep a read state",
    Capability.STARS: "keep stars",
    Capability.KEYWORDS: "keep keywords",
    Capability.FOLDERS: "create, rename or delete folders",
    Capability.MOVE: "move messages",
    Capability.TRASH: "delete into a trash",
    Capability.PURGE: "delete messages for good",
    Capability.LABELS: "keep a message in several folders",
    Capability.SEARCH: "search or filter its messages",
    Capability.DRAFTS: "keep drafts",
    Capability.SEND: "send",
    Capability.SENT_COPY: "keep a copy of what it sends",
    Capability.THREADS: "keep threads",
    Capability.PUSH: "report changes by itself",
    Capability.EXTERNAL_CHANGES: "see the changes of other mail programs",
    Capability.REFUSED: "name refused recipients while sending",
}

_MARKS = frozenset(Mark)


def for_update(changes: MessageUpdate) -> Needs:
    """What a change of messages needs: each field its capability, a mark
    that it be written, several folders ``labels``."""
    found: set[Capability] = set()
    marks: set[Mark] = set()
    if changes.unread is not None:
        found.add(Capability.READ_STATE)
    if changes.starred is not None:
        found.add(Capability.STARS)
    if changes.keywords is not None:
        # A new list takes off what it leaves out.
        found.add(Capability.KEYWORDS)
    for keyword in _touched(changes):
        if keyword.lower() in _MARKS:
            marks.add(Mark(keyword.lower()))
        else:
            found.add(Capability.KEYWORDS)
    if changes.changes_folders:
        found.add(Capability.MOVE)
        several = changes.folder_ids is not None and len(set(changes.folder_ids)) > 1
        if several or changes.adds_or_removes_folders:
            found.add(Capability.LABELS)
    return Needs(frozenset(found), frozenset(marks))


def for_delete(permanent: bool) -> Needs:
    return needs(Capability.PURGE if permanent else Capability.TRASH)


def for_list(search: MessageFilter | None) -> Needs:
    """A list narrowed by any filter needs ``search``."""
    if search is not None and search.model_dump(exclude_none=True):
        return needs(Capability.SEARCH)
    return NOTHING


def lacking(abilities: Abilities, wanted: Needs) -> NotSupportedError | None:
    """The error for what ``abilities`` leave out of ``wanted``, if any."""
    missing = sorted(c for c in wanted.capabilities if not abilities.has(c))
    if missing:
        return NotSupportedError(
            "this account cannot " + " or ".join(_CANNOT[c] for c in missing)
        )
    unwritten = sorted(m for m in wanted.marks if m not in abilities.marks.written)
    if unwritten:
        return NotSupportedError(
            "this account cannot set or take off " + ", ".join(unwritten)
        )
    return None


def _touched(changes: MessageUpdate) -> Iterable[str]:
    for keywords in (changes.keywords, changes.add_keywords, changes.remove_keywords):
        yield from keywords or ()


def writes(adapter: Reads) -> Writes:
    if isinstance(adapter, Writes):
        return adapter
    raise NotSupportedError(
        "this account keeps no folders, read state, stars or keywords to change"
    )


def deletes(adapter: Reads) -> Deletes:
    if isinstance(adapter, Deletes):
        return adapter
    raise NotSupportedError("this account cannot delete messages")


def drafts(adapter: Reads) -> Drafts:
    if isinstance(adapter, Drafts):
        return adapter
    raise NotSupportedError("this account keeps no drafts")


def sends(adapter: Reads) -> Sends:
    if isinstance(adapter, Sends):
        return adapter
    raise NotSupportedError("this account cannot send")


def watches(adapter: Reads) -> Watches:
    if isinstance(adapter, Watches):
        return adapter
    raise NotSupportedError("this account reports no change by itself: it is polled")


def threads(adapter: Reads) -> Threads:
    if isinstance(adapter, Threads):
        return adapter
    raise NotSupportedError("this account keeps no threads")


def summaries(adapter: Reads) -> Summaries:
    if isinstance(adapter, Summaries):
        return adapter
    raise NotSupportedError("this account keeps no threads")


def deltas(adapter: Reads) -> Deltas:
    if isinstance(adapter, Deltas):
        return adapter
    raise NotSupportedError(
        "this account tells no changes since a point: its folders are compared"
    )
