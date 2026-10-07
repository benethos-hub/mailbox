"""Messages of several accounts in one list, merged newest first.

Each account is read in windows of its own pages. The cursor carries
where each account stands (``merge``). Accounts the caller may not read
are left out without a word, like in ``list_accounts``. An account that
fails leaves the page incomplete, it does not fail the request.
"""

from __future__ import annotations

from ...data.models import (
    AccountFailure,
    FolderRole,
    MessageFilter,
    MessagePage,
    MessageSummary,
    Page,
)
from ..rights import Access
from . import merge
from .calls import Calls
from .fingerprint import fingerprint
from .reach import Reach, reach_of

OPERATION = "list_all_messages"


class AcrossAccounts:
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    async def list_all_messages(
        self,
        access: Access,
        *,
        account_ids: list[str] | None,
        folder_role: FolderRole | None,
        search: MessageFilter | None = None,
        limit: int,
        cursor: str | None,
    ) -> MessagePage:
        failures: list[AccountFailure] = []
        visible, reaches = await self._visible(access, account_ids, failures)
        query = fingerprint(folder_role, search)
        if cursor:
            positions = {
                a: p
                for a, p in merge.decode_cursor(cursor, query).items()
                if a in visible
            }
        else:
            positions = await self._start(visible, folder_role, failures, reaches)
        chunks = await merge.per_account(
            [a for a, p in positions.items() if not p.done],
            lambda a: self._window(a, positions[a], search, limit, reaches.get(a)),
            failures,
        )
        # An account that failed is named in ``failures`` and keeps its place
        # while others deliver, to join again later. Once every account
        # still open has failed, the list ends: a cursor that promises more
        # from accounts that do not answer would promise it forever.
        if not chunks:
            positions = {
                a: merge.Position(p.folder_id, None, 0, done=True)
                for a, p in positions.items()
            }
        items = await self._merged(chunks, positions, limit)
        more = any(not p.done for p in positions.values())
        return MessagePage(
            items=items,
            next_cursor=merge.encode_cursor(positions, query) if more else None,
            incomplete=failures,
        )

    async def _visible(
        self,
        access: Access,
        account_ids: list[str] | None,
        failures: list[AccountFailure],
    ) -> tuple[list[str], dict[str, Reach | None]]:
        """The accounts the caller may list, and the reach of those whose
        grants name folders. An account whose folders cannot be read now
        fails like any other."""
        existing = self._calls.ids()
        visible = access.filter(
            OPERATION, (a for a in account_ids or existing if a in existing)
        )
        narrowed = [a for a in visible if access.folder_scopes(OPERATION, a)]
        reaches = await merge.per_account(
            narrowed,
            lambda a: reach_of(self._calls, access, OPERATION, a),
            failures,
        )
        return [a for a in visible if a not in narrowed or a in reaches], reaches

    async def _start(
        self,
        account_ids: list[str],
        role: FolderRole | None,
        failures: list[AccountFailure],
        reaches: dict[str, Reach | None],
    ) -> dict[str, merge.Position]:
        if role is None:
            return {a: merge.Position(None, None, 0) for a in account_ids}
        folders = await merge.per_account(
            account_ids,
            lambda a: self._calls.call(a, lambda p: p.list_folders()),
            failures,
        )
        positions = {}
        for account_id, found in folders.items():
            match = next((f for f in found if f.role is role), None)
            reach = reaches.get(account_id)
            if match is not None and (reach is None or match.id in reach.ids):
                positions[account_id] = merge.Position(match.id, None, 0)
        return positions

    async def _window(
        self,
        account_id: str,
        position: merge.Position,
        search: MessageFilter | None,
        limit: int,
        reach: Reach | None = None,
    ) -> list[merge.Chunk]:
        """At least ``limit`` of the account's next messages, or all it has
        left, so that merging by date cannot skip a newer one. Out of
        ``reach`` left out: the same each time a page is read, so the
        offsets into it hold."""

        async def page(cursor: str | None) -> Page[MessageSummary]:
            found = await self._calls.call(
                account_id,
                lambda p: p.list_messages(
                    position.folder_id,
                    limit=limit,
                    cursor=cursor,
                    search=search,
                ),
            )
            return found if reach is None else in_reach(found, reach)

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

    async def _merged(
        self,
        chunks: dict[str, list[merge.Chunk]],
        positions: dict[str, merge.Position],
        limit: int,
    ) -> list[MessageSummary]:
        """The newest ``limit`` of the windows, under our ids. Each
        account's position moves past what it gave."""
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
            published[account_id] = await self._calls.published(account_id, mine)
        return [published[owner].pop(0) for _, owner in taken]


def in_reach(page: Page[MessageSummary], reach: Reach) -> Page[MessageSummary]:
    """The page without the messages out of reach."""
    return Page[MessageSummary](
        items=[item for item in page.items if reach.sees(item.folder_ids)],
        next_cursor=page.next_cursor,
    )
