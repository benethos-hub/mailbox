"""What the tests of categorization share: a list from its entries, and a list
refused."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.groups import Groups, load_groups
from benethos_mailbox_agents.errors import ConfigError


def groups(*entries: dict[str, Any]) -> Groups:
    return Groups.model_validate({"groups": list(entries)})


def refused(tmp_path: Path, entries: list[dict[str, Any]], says: str) -> None:
    """The list of ``entries`` is refused with ``says``, and the message
    quotes no rule and no topic."""
    path = tmp_path / "categorization.json"
    path.write_text(json.dumps({"groups": entries}), encoding="utf-8")

    with pytest.raises(ConfigError, match="categorization.json") as raised:
        load_groups(path)

    assert says in raised.value.message
    for entry in entries:
        for rule in entry.get("senders", []):
            assert rule not in raised.value.message
        topic = entry.get("topic")
        if isinstance(topic, str) and topic.strip():
            assert topic.strip() not in raised.value.message
