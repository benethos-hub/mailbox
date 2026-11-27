"""The list of filing: what it refuses, and where it puts a message."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.filing.rules import Rules, Target, load_rules
from benethos_mailbox_agents.errors import ConfigError

PARTNER = {"keywords": ["agent-partner-cloudhost"], "move": "Providers/CloudHost"}
KIND = {"keywords": ["agent-invoice"], "below": "Invoices"}


def _write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "filing.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _rules(*rules: dict[str, Any]) -> Rules:
    return Rules.model_validate({"rules": list(rules)})


# Every text of the owner the lists below hold: none may stand in a message.
OWN_TEXT = ("cloudhost", "Providers", "Invoices", "Secret-Folder", "agent-secret")


@pytest.mark.parametrize(
    ("data", "says"),
    [
        ({"rules": []}, "rules: Tuple should have at least 1 item"),
        ({"rules": [{"keywords": ["agent-secret"]}]}, "rule names move or below"),
        (
            {"rules": [{"keywords": ["agent-secret"], "move": "A", "below": "B"}]},
            "rule names move or below",
        ),
        ({"rules": [{"keywords": [], "move": "A"}]}, "rules.0.keywords"),
        (
            {"rules": [{"keywords": ["Agent-Secret"], "move": "A"}]},
            "lower case letters, digits and dashes",
        ),
        (
            {"rules": [{"keywords": ["agent-secret"], "move": "Secret-Folder/../x"}]},
            "names between /",
        ),
        (
            {"rules": [{"keywords": ["agent-secret"], "move": "A", "copy": "B"}]},
            "rules.0.copy: Extra inputs are not permitted",
        ),
        (
            {"on": {"keywords": ["agent-*-x"]}, "rules": [PARTNER]},
            "a keyword of on is lower case",
        ),
        (
            {
                "rules": [
                    {"keywords": ["agent-secret"], "move": "Secret-Folder/A"},
                    {"keywords": ["agent-other"], "move": "secret-folder/B"},
                ]
            },
            "rule 2: a folder differs from one of rule 1 in case only",
        ),
    ],
)
def test_a_wrong_list_is_refused_by_the_place_of_its_rule(
    tmp_path: Path, data: Any, says: str
) -> None:
    with pytest.raises(ConfigError, match="the filing list filing.json") as raised:
        load_rules(_write(tmp_path, data))

    message = str(raised.value)
    assert says in message
    assert not any(text in message for text in OWN_TEXT)


def test_a_file_that_is_no_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "filing.json"
    path.write_text("{rules", encoding="utf-8")

    with pytest.raises(ConfigError, match="is no JSON"):
        load_rules(path)


def test_a_list_read_from_its_file(tmp_path: Path) -> None:
    found = load_rules(_write(tmp_path, {"rules": [PARTNER, KIND]}))

    assert found.rules[0].move == "Providers/CloudHost"
    assert found.rules[1].below == "Invoices"


def test_without_on_the_list_waits_for_the_keywords_of_its_rules() -> None:
    found = _rules(PARTNER, KIND)

    assert found.waits_for("Agent-Invoice")
    assert found.waits_for("agent-partner-cloudhost")
    assert not found.waits_for("agent-partner-telco")


def test_on_names_what_the_list_waits_for() -> None:
    found = Rules.model_validate(
        {"on": {"keywords": ["agent-categorized-*"]}, "rules": [PARTNER]}
    )

    assert found.waits_for("agent-categorized-bookkeeping")
    assert not found.waits_for("agent-partner-cloudhost")


BOTH = ("agent-partner-cloudhost", "agent-invoice")


@pytest.mark.parametrize(
    ("keywords", "in_inbox", "own", "target"),
    [
        (BOTH, True, None, Target("Providers/CloudHost/Invoices", move=1, below=2)),
        (
            ("agent-partner-cloudhost",),
            True,
            None,
            Target("Providers/CloudHost", move=1),
        ),
        (("agent-invoice",), True, None, None),
        (
            ("agent-invoice",),
            False,
            "Projects/Atlas",
            Target("Projects/Atlas/Invoices", below=2),
        ),
        (
            ("agent-invoice",),
            False,
            "Projects/Invoices",
            Target("Projects/Invoices", below=2),
        ),
        (BOTH, False, "Projects/Atlas", Target("Projects/Atlas/Invoices", below=2)),
        (("agent-partner-cloudhost",), False, "Projects/Atlas", None),
        (BOTH, False, None, None),
        ((), True, None, None),
    ],
)
def test_where_a_message_goes(
    keywords: tuple[str, ...], in_inbox: bool, own: str | None, target: Target | None
) -> None:
    found = _rules(PARTNER, KIND)

    assert found.target(keywords, in_inbox=in_inbox, own_folder=own) == target


def test_a_move_that_ends_in_the_below_takes_none_more() -> None:
    found = _rules(
        {"keywords": ["agent-invoice"], "move": "Bookkeeping/Invoices"}, KIND
    )

    assert found.target(("agent-invoice",), in_inbox=True, own_folder=None) == Target(
        "Bookkeeping/Invoices", move=1, below=2
    )


def test_the_first_move_that_fits_wins() -> None:
    found = _rules(
        {"keywords": ["agent-partner-cloudhost"], "move": "Providers/CloudHost"},
        {"keywords": ["agent-partner-cloudhost"], "move": "Other"},
    )

    assert found.target(
        ("agent-partner-cloudhost",), in_inbox=True, own_folder=None
    ) == Target("Providers/CloudHost", move=1)


def test_the_folders_the_list_may_make() -> None:
    found = _rules(PARTNER, KIND)

    assert found.folders() == {
        "Providers",
        "Providers/CloudHost",
        "Providers/CloudHost/Invoices",
    }
    assert found.belows() == {"Invoices"}
