"""The steps of the state file: what each step of a message answered."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..records import MessageRef, Step, StepResult
from .rows import _Rows, _text


class _Steps(_Rows):
    """What each step of a message answered."""

    def add_step(self, ref: MessageRef, result: StepResult, model_alias: str) -> None:
        self._write(
            "INSERT INTO steps (account_id, message_id, step, prompt_version, "
            "model_alias, model, result, tokens_in, tokens_out, duration_ms, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ref.account_id,
            ref.message_id,
            result.step,
            result.prompt_version,
            model_alias,
            result.model,
            json.dumps(result.result, sort_keys=True, ensure_ascii=False),
            result.tokens_in,
            result.tokens_out,
            result.duration_ms,
            _text(result.at),
        )

    def step(
        self, ref: MessageRef, step: Step, prompt_version: str, model_alias: str
    ) -> StepResult | None:
        """The latest result of ``step`` for this message under this prompt
        version and model alias, the key of idempotency."""
        row = self._one(
            _STEP_SQL + " WHERE account_id = ? AND message_id = ? "
            "AND step = ? AND prompt_version = ? AND model_alias = ? "
            "ORDER BY id DESC LIMIT 1",
            ref.account_id,
            ref.message_id,
            step,
            prompt_version,
            model_alias,
        )
        return _step(row) if row else None

    def steps(self, ref: MessageRef) -> list[StepResult]:
        """Every step of a message, in the order they ran."""
        rows = self._all(
            _STEP_SQL + " WHERE account_id = ? AND message_id = ? ORDER BY id",
            ref.account_id,
            ref.message_id,
        )
        return [_step(row) for row in rows]

    def model_calls_since(self, since: datetime) -> int:
        row = self._one(
            "SELECT COUNT(*) FROM steps WHERE step = ? AND at >= ?",
            "model",
            _text(since),
        )
        return int(row[0])

    def labels_since(self, since: datetime) -> dict[str, int]:
        """How many decisions named each label since ``since``. A message
        decided twice, as by ``backfill``, counts twice."""
        rows = self._all(
            "SELECT result FROM steps WHERE step = ? AND at >= ?",
            "decision",
            _text(since),
        )
        found: dict[str, int] = {}
        for (result,) in rows:
            label = str(json.loads(result).get("label", ""))
            found[label] = found.get(label, 0) + 1
        return dict(sorted(found.items()))

    def model_calls_for(self, ref: MessageRef, since: datetime) -> int:
        """How many model calls were made for one message since ``since``."""
        row = self._one(
            "SELECT COUNT(*) FROM steps WHERE account_id = ? AND message_id = ? "
            "AND step = ? AND at >= ?",
            ref.account_id,
            ref.message_id,
            "model",
            _text(since),
        )
        return int(row[0])


# The columns each kind of row is read with, in the order of its reader
# below.
_STEP_SQL = (
    "SELECT step, prompt_version, model, result, tokens_in, tokens_out, "
    "duration_ms, at FROM steps"
)


def _step(row: Any) -> StepResult:
    return StepResult(
        step=row[0],
        prompt_version=row[1],
        model=row[2],
        result=json.loads(row[3]),
        tokens_in=row[4],
        tokens_out=row[5],
        duration_ms=row[6],
        at=datetime.fromisoformat(row[7]),
    )
