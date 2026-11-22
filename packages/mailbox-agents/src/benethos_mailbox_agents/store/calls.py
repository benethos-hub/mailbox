"""The kept model calls of the state file, docs/mailbox-agents/concept/state.md."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..records import MessageRef
from .rows import _Rows, _text


class _Calls(_Rows):
    """The model calls kept for a while, docs/mailbox-agents/concept/state.md."""

    def add_call(
        self, ref: MessageRef, request: Any, answer: Any, now: datetime
    ) -> None:
        self._write(
            "INSERT INTO calls (account_id, message_id, request, answer, at) "
            "VALUES (?, ?, ?, ?, ?)",
            ref.account_id,
            ref.message_id,
            # Escaped, so a lone surrogate in what the gateway answered
            # cannot end the write.
            json.dumps(request),
            json.dumps(answer),
            _text(now),
        )

    def purge_calls(self, before: datetime) -> int:
        """Delete the kept calls older than ``before``. Answers how many.
        After a deletion the write-ahead log is written back and emptied, so
        the deleted text is gone from it as well."""
        purged = self._write("DELETE FROM calls WHERE at < ?", _text(before))
        if purged:
            self._one("PRAGMA wal_checkpoint(TRUNCATE)")
        return purged

    def count_calls(self) -> int:
        return int(self._one("SELECT COUNT(*) FROM calls")[0])
