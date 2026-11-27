"""The profile of the agent that writes the file, one row: what a
reader from outside, such as the cockpit, cannot know without the
settings of the worker."""

from __future__ import annotations

import json
from decimal import Decimal

from ..records import Profile
from .rows import _Rows, _text, _time

# The schema version that brought the table, migration 4.
_SINCE = 4

_COLUMNS = (
    "agent, instance, agent_version, package_version, stage, accounts, "
    "keyword, poll_seconds, gateway_timeout_seconds, model_alias, "
    "prompt_version, started"
)


def _decimal(seconds: float) -> str:
    """``seconds`` as decimal text without an exponent, read back exactly."""
    return format(Decimal(repr(seconds)), "f")


class _Profile(_Rows):
    def set_profile(self, profile: Profile) -> None:
        """Keep ``profile`` as the one row, in place of the one before."""
        updates = ", ".join(
            f"{column} = excluded.{column}" for column in _COLUMNS.split(", ")
        )
        self._write(
            f"INSERT INTO profile (id, {_COLUMNS}) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}",
            profile.agent,
            profile.instance,
            profile.agent_version,
            profile.package_version,
            profile.stage,
            json.dumps(list(profile.accounts)),
            profile.keyword,
            _decimal(profile.poll_seconds),
            _decimal(profile.gateway_timeout_seconds),
            profile.model_alias,
            profile.prompt_version,
            _text(profile.started),
        )

    def profile(self) -> Profile | None:
        """The profile the worker wrote, None for a file older than the
        table or one no worker has started on since."""
        if self.version < _SINCE:
            return None
        row = self._one(f"SELECT {_COLUMNS} FROM profile WHERE id = 1")
        if row is None:
            return None
        return Profile(
            agent=row[0],
            instance=row[1],
            agent_version=row[2],
            package_version=row[3],
            stage=row[4],
            accounts=tuple(json.loads(row[5])),
            keyword=row[6],
            poll_seconds=float(row[7]),
            gateway_timeout_seconds=float(row[8]),
            model_alias=row[9],
            prompt_version=row[10],
            started=_time(row[11]),
        )
