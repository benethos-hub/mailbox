"""The kept model calls of the state file, docs/mailbox-agents/concept/state.md."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from ..records import MessageRef
from .rows import _named, _Rows, _text
from .schema import calls


class _Calls(_Rows):
    """The model calls kept for a while, docs/mailbox-agents/concept/state.md."""

    def add_call(
        self, ref: MessageRef, request: Any, answer: Any, now: datetime
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                sa.insert(calls).values(
                    account_id=ref.account_id,
                    message_id=ref.message_id,
                    # Escaped, so a lone surrogate in what the gateway
                    # answered cannot end the write.
                    request=json.dumps(request),
                    answer=json.dumps(answer),
                    at=_text(now),
                )
            )

    def purge_calls(self, before: datetime) -> int:
        """Delete the kept calls older than ``before``. Answers how many.
        After a deletion the file shrinks and its write-ahead log is
        written back and emptied, so the deleted text is gone from both."""
        with _named(self._name):
            return self._db.purge(calls, "at", before)

    def count_calls(self) -> int:
        with self._conn() as conn:
            return int(
                conn.execute(sa.select(sa.func.count()).select_from(calls)).scalar_one()
            )
