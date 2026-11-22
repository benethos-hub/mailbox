"""The gold format and its loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.evaluation.gold import load_gold
from benethos_mailbox_agents.records import MessageRef

from ..agents_fake import ACCOUNT, invented

DATA = Path(__file__).resolve().parent.parent / "data"


def test_the_invented_gold_set_loads_and_names_invented_mail() -> None:
    items = load_gold(DATA / "gold-invoices.jsonl")
    ids = {m["id"] for m in invented()}

    assert len(items) == 10
    assert {item.message_id for item in items} == ids
    assert items[0].ref == MessageRef(account_id=ACCOUNT, message_id="inv-cloudhost")
    assert items[0].fields == {"near_miss": None}


def _gold(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_comments_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = _gold(
        tmp_path,
        "# a comment",
        "",
        '{"account_id": "a", "message_id": "m", "label": "other"}',
    )

    assert [item.label for item in load_gold(path)] == ["other"]


def test_a_gold_file_with_the_mark_of_utf8_is_read(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"account_id": "a", "message_id": "m", "label": "other"}\n',
        encoding="utf-8-sig",
    )

    assert [item.label for item in load_gold(path)] == ["other"]


@pytest.mark.parametrize(
    ("lines", "said"),
    [
        (["not json"], "line 1: JSONDecodeError"),
        (['{"account_id": "a", "message_id": "m"}'], "line 1: label: Field required"),
        (['{"account_id": "a", "message_id": "m", "label": "x", "extra": 1}'], "extra"),
        (
            [
                '{"account_id": "a", "message_id": "m", "label": "x"}',
                '{"account_id": "a", "message_id": "m", "label": "y"}',
            ],
            "line 2: the message is there twice",
        ),
        (["# only a comment"], "holds no labelled message"),
    ],
)
def test_a_wrong_line_is_named(tmp_path: Path, lines: list[str], said: str) -> None:
    with pytest.raises(ConfigError, match=said):
        load_gold(_gold(tmp_path, *lines))


def test_a_missing_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no gold file"):
        load_gold(tmp_path / "none.jsonl")
