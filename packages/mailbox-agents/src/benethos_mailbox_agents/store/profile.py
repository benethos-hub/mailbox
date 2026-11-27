"""The profile of the agent that writes the file, one row: what a
reader from outside, such as the cockpit, cannot know without the
settings of the worker."""

from __future__ import annotations

import json
from decimal import Decimal

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

from ..records import Profile
from .rows import _Rows, _text, _time
from .schema import profile as table

_p = table.c


def _decimal(seconds: float) -> str:
    """``seconds`` as decimal text without an exponent, read back exactly."""
    return format(Decimal(repr(seconds)), "f")


class _Profile(_Rows):
    def set_profile(self, profile: Profile) -> None:
        """Keep ``profile`` as the one row, in place of the one before."""
        values = {
            "id": 1,
            "agent": profile.agent,
            "instance": profile.instance,
            "agent_version": profile.agent_version,
            "package_version": profile.package_version,
            "stage": profile.stage,
            "accounts": json.dumps(list(profile.accounts)),
            "keyword": profile.keyword,
            "poll_seconds": _decimal(profile.poll_seconds),
            "gateway_timeout_seconds": _decimal(profile.gateway_timeout_seconds),
            "model_alias": profile.model_alias,
            "prompt_version": profile.prompt_version,
            "started": _text(profile.started),
        }
        with self._conn() as conn:
            conn.execute(
                dialect.insert_or_update(table, ["id"], None, conn.dialect).values(
                    values
                )
            )

    def profile(self) -> Profile | None:
        """The profile the worker wrote, None for a file no worker has
        started on since the table came."""
        with self._conn() as conn:
            row = conn.execute(sa.select(table).where(_p.id == 1)).mappings().first()
        if row is None:
            return None
        return Profile(
            agent=row["agent"],
            instance=row["instance"],
            agent_version=row["agent_version"],
            package_version=row["package_version"],
            stage=row["stage"],
            accounts=tuple(json.loads(row["accounts"])),
            keyword=row["keyword"],
            poll_seconds=float(row["poll_seconds"]),
            gateway_timeout_seconds=float(row["gateway_timeout_seconds"]),
            model_alias=row["model_alias"],
            prompt_version=row["prompt_version"],
            started=_time(row["started"]),
        )
