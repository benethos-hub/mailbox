"""Following a message the provider no longer finds where the index
says: one sync pass, at most once per pass (CONCEPT 4.1). The other rule
of this kind, one pass before a list, is ``SyncService``'s own."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import SyncService


class Gone:
    """Per account, the messages looked up in vain after a pass: our id
    and the provider's. Forgotten with the next pass."""

    def __init__(self, sync: SyncService) -> None:
        self._sync = sync
        self._after: dict[str, tuple[int, set[tuple[str, str]]]] = {}

    def forget(self, account_id: str) -> None:
        """An account is deleted: what was looked up in it goes."""
        self._after.pop(account_id, None)

    async def after_a_pass(
        self, account_id: str, natives: dict[str, str]
    ) -> dict[str, str]:
        """Messages the provider did not find where the index says: one sync
        pass, and the new place of those that moved. One looked up in vain
        since the last pass gets no pass of its own: a caller that names a
        stale id again and again does not sync the account each time, nor
        after a pass given up, which counts as none: until the next pass."""
        if self._known(account_id, self._passes(account_id), natives):
            return {}
        await self._sync.sync_account(account_id)
        now = self._sync.natives(account_id, list(natives))
        moved = {i: n for i, n in now.items() if n and n != natives[i]}
        self._note(
            account_id,
            self._passes(account_id),
            {i: n for i, n in natives.items() if i not in moved},
        )
        return moved

    def _passes(self, account_id: str) -> int:
        return self._sync.state(account_id).passes

    def _known(self, account_id: str, passes: int, natives: dict[str, str]) -> bool:
        """Whether every one of them was looked up in vain since pass
        ``passes``."""
        noted = self._after.get(account_id)
        return (
            noted is not None
            and noted[0] == passes
            and set(natives.items()) <= noted[1]
        )

    def _note(self, account_id: str, passes: int, natives: dict[str, str]) -> None:
        noted = self._after.get(account_id)
        if noted is None or noted[0] != passes:
            noted = (passes, set())
            self._after[account_id] = noted
        noted[1].update(natives.items())
