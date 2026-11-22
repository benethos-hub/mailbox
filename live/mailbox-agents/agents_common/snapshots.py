"""How the messages of the test account lie: their folders and keywords,
taken before a check and put back after it."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from benethos_mailbox_agents.errors import MessageGoneError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox

from .settings import DAYS

# Each message of the inbox: its folder ids and its keywords, each sorted.
Snapshot = dict[MessageRef, tuple[tuple[str, ...], tuple[str, ...]]]


async def inbox_snapshot(mailbox: Mailbox, settings: Settings) -> Snapshot:
    """Each message of the inbox of the last :data:`DAYS` days: its folders
    and keywords."""
    since = date.today() - timedelta(days=DAYS)
    refs = await mailbox.recent(since, settings.accounts, roles=("inbox",))
    return await snapshot(mailbox, refs)


async def snapshot(mailbox: Mailbox, refs: Iterable[MessageRef]) -> Snapshot:
    """The folders and keywords of each message of ``refs`` as it lies now,
    fetched one by one. A message gone is left out."""
    found: Snapshot = {}
    for ref in refs:
        try:
            message = await mailbox.message(ref)
        except MessageGoneError:
            continue
        found[ref] = (
            tuple(sorted(f.id for f in message.folders)),
            tuple(sorted(message.keywords)),
        )
    return found


async def put_back(mailbox: Mailbox, before: Snapshot, *keywords: str) -> int:
    """Put each message of ``before`` back as it lay: into its folder when
    it lies elsewhere now, then with each of ``keywords`` taken off that
    was not on it. Taken from the snapshot, not from the actions of a state
    file, so a run cut short in the middle is put back too. Each message is
    read once: a second look right after a move may still see the folder
    before it. Answers how many messages were moved back."""
    moved = 0
    for ref, (folders, found) in (await snapshot(mailbox, before)).items():
        was_folders, was_keywords = before[ref]
        if folders != was_folders and was_folders:
            await mailbox.move(ref, was_folders[0])
            moved += 1
        on = {k.casefold() for k in found}
        was = {k.casefold() for k in was_keywords}
        for keyword in keywords:
            if keyword.casefold() in on and keyword.casefold() not in was:
                await mailbox.remove_keyword(ref, keyword)
    return moved
