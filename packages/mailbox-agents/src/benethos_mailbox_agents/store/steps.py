"""The steps of the state file: what each step of a message answered."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from ..records import MessageRef, Step, StepResult
from .rows import _Rows, _text
from .schema import steps

_s = steps.c


class _Steps(_Rows):
    """What each step of a message answered."""

    def add_step(self, ref: MessageRef, result: StepResult, model_alias: str) -> None:
        with self._conn() as conn:
            conn.execute(
                sa.insert(steps).values(
                    account_id=ref.account_id,
                    message_id=ref.message_id,
                    step=result.step,
                    prompt_version=result.prompt_version,
                    model_alias=model_alias,
                    model=result.model,
                    result=json.dumps(
                        result.result, sort_keys=True, ensure_ascii=False
                    ),
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    duration_ms=result.duration_ms,
                    at=_text(result.at),
                )
            )

    def step(
        self, ref: MessageRef, step: Step, prompt_version: str, model_alias: str
    ) -> StepResult | None:
        """The latest result of ``step`` for this message under this prompt
        version and model alias, the key of idempotency."""
        query = (
            _select()
            .where(
                *_of(ref),
                _s.step == step,
                _s.prompt_version == prompt_version,
                _s.model_alias == model_alias,
            )
            .order_by(_s.id.desc())
            .limit(1)
        )
        with self._conn() as conn:
            row = conn.execute(query).first()
        return _step(row) if row else None

    def steps(self, ref: MessageRef) -> list[StepResult]:
        query = _select().where(*_of(ref)).order_by(_s.id)
        with self._conn() as conn:
            return [_step(row) for row in conn.execute(query)]

    def model_calls_since(self, since: datetime) -> int:
        query = sa.select(sa.func.count()).where(
            _s.step == "model", _s.at >= _text(since)
        )
        with self._conn() as conn:
            return int(conn.execute(query).scalar_one())

    def labels_since(self, since: datetime) -> dict[str, int]:
        """How many decisions named each label since ``since``. A message
        decided twice, as by ``backfill``, counts twice."""
        query = sa.select(_s.result).where(_s.step == "decision", _s.at >= _text(since))
        found: dict[str, int] = {}
        with self._conn() as conn:
            for (result,) in conn.execute(query):
                label = str(json.loads(result).get("label", ""))
                found[label] = found.get(label, 0) + 1
        return dict(sorted(found.items()))

    def model_calls_for(self, ref: MessageRef, since: datetime) -> int:
        """How many model calls were made for one message since ``since``."""
        query = sa.select(sa.func.count()).where(
            *_of(ref), _s.step == "model", _s.at >= _text(since)
        )
        with self._conn() as conn:
            return int(conn.execute(query).scalar_one())


def _select() -> sa.Select[Any]:
    return sa.select(
        _s.step,
        _s.prompt_version,
        _s.model,
        _s.result,
        _s.tokens_in,
        _s.tokens_out,
        _s.duration_ms,
        _s.at,
    )


def _of(ref: MessageRef) -> tuple[sa.ColumnElement[bool], ...]:
    return (_s.account_id == ref.account_id, _s.message_id == ref.message_id)


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
